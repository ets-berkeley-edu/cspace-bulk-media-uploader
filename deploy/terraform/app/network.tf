# The network, one of two ways (variables.tf, vpc_id):
# - its own VPC (vpc_id empty; a personal account): public subnets for the tasks, which have public IPs for outbound
#   HTTPS, private subnets for the load balancer, no NAT gateway;
# - an existing VPC (vpc_id set, such as Operations' shared dev/QA VPC): the tasks in its private subnets without
#   public IPs, out through its NAT gateway, and the load balancer in the subnets given (private ones for an internal
#   one behind CloudFront, public ones with front_door alb). Nothing in that VPC
#   is created or changed except the BMU's security groups and, if asked, the S3 and DynamoDB gateway endpoints.

locals {
  own_vpc = var.vpc_id == ""

  vpc_id           = local.own_vpc ? aws_vpc.main[0].id : data.aws_vpc.existing[0].id
  app_subnet_ids   = local.own_vpc ? aws_subnet.public[*].id : [for s in data.aws_subnet.app : s.id]
  lb_subnet_ids    = local.own_vpc ? aws_subnet.private[*].id : [for s in data.aws_subnet.lb : s.id]
  assign_public_ip = local.own_vpc

  # Gateway endpoints: always in its own VPC; in an existing one only when it has none yet.
  gateway_endpoints     = local.own_vpc || var.create_gateway_endpoints ? 1 : 0
  endpoint_route_tables = local.own_vpc ? aws_route_table.public[*].id : distinct([for t in data.aws_route_table.app : t.id])
}

# ---- An existing VPC ----

data "aws_vpc" "existing" {
  count = local.own_vpc ? 0 : 1
  id    = var.vpc_id
}

data "aws_subnet" "app" {
  for_each = toset(var.app_subnet_ids)
  id       = each.value

  lifecycle {
    postcondition {
      condition     = self.vpc_id == var.vpc_id
      error_message = "app subnet ${each.value} isn't in ${var.vpc_id}."
    }
  }
}

# Without lb_subnet_ids (front_door cloudfront only), the internal load balancer goes in the app subnets.
data "aws_subnet" "lb" {
  for_each = toset(length(var.lb_subnet_ids) > 0 ? var.lb_subnet_ids : var.app_subnet_ids)
  id       = each.value

  lifecycle {
    postcondition {
      condition     = self.vpc_id == var.vpc_id
      error_message = "load balancer subnet ${each.value} isn't in ${var.vpc_id}."
    }
  }
}

data "aws_route_table" "app" {
  for_each  = !local.own_vpc && var.create_gateway_endpoints ? toset(var.app_subnet_ids) : toset([])
  subnet_id = each.value
}

# ---- Its own VPC ----

resource "aws_vpc" "main" {
  count                = local.own_vpc ? 1 : 0
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = local.name }
}

resource "aws_internet_gateway" "main" {
  count  = local.own_vpc ? 1 : 0
  vpc_id = aws_vpc.main[0].id

  tags = { Name = local.name }
}

# The tasks: public IPs for outbound HTTPS, nothing inbound from outside (see security.tf).
resource "aws_subnet" "public" {
  count = local.own_vpc ? 2 : 0

  vpc_id            = aws_vpc.main[0].id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone = local.azs[count.index]

  tags = { Name = "${local.name}-public-${count.index + 1}" }
}

# The load balancer and CloudFront's VPC origin.
resource "aws_subnet" "private" {
  count = local.own_vpc ? 2 : 0

  vpc_id            = aws_vpc.main[0].id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, 10 + count.index)
  availability_zone = local.azs[count.index]

  tags = { Name = "${local.name}-private-${count.index + 1}" }
}

resource "aws_route_table" "public" {
  count  = local.own_vpc ? 1 : 0
  vpc_id = aws_vpc.main[0].id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main[0].id
  }

  tags = { Name = "${local.name}-public" }
}

resource "aws_route_table_association" "public" {
  count = local.own_vpc ? 2 : 0

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[0].id
}

# No route out: only the VPC itself.
resource "aws_route_table" "private" {
  count  = local.own_vpc ? 1 : 0
  vpc_id = aws_vpc.main[0].id

  tags = { Name = "${local.name}-private" }
}

resource "aws_route_table_association" "private" {
  count = local.own_vpc ? 2 : 0

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[0].id
}

# ---- Either way ----

# S3 and DynamoDB traffic stays inside AWS (and, in an existing VPC, off its NAT gateway).
resource "aws_vpc_endpoint" "s3" {
  count             = local.gateway_endpoints
  vpc_id            = local.vpc_id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = local.endpoint_route_tables

  tags = { Name = "${local.name}-s3" }
}

resource "aws_vpc_endpoint" "dynamodb" {
  count             = local.gateway_endpoints
  vpc_id            = local.vpc_id
  service_name      = "com.amazonaws.${var.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = local.endpoint_route_tables

  tags = { Name = "${local.name}-dynamodb" }
}

# With front_door alb, the staging bucket takes uploads only from allowed_cidrs or through the VPC's S3 gateway
# endpoint, which the tasks' own writes use (s3.tf). In an existing VPC with its own endpoint (Operations'), it is
# looked up: the plan fails if the VPC has none. Its route tables must include the app subnets', or the tasks' writes
# would leave through the NAT gateway and be refused (deploy/README.md, "Deploying into an existing VPC").
data "aws_vpc_endpoint" "s3" {
  count        = local.alb && local.gateway_endpoints == 0 ? 1 : 0
  vpc_id       = local.vpc_id
  service_name = "com.amazonaws.${var.region}.s3"

  filter {
    name   = "vpc-endpoint-type"
    values = ["Gateway"]
  }
}

locals {
  s3_endpoint_id = local.alb ? (local.gateway_endpoints == 1 ? aws_vpc_endpoint.s3[0].id : data.aws_vpc_endpoint.s3[0].id) : ""
}

# Environments deployed before the existing-VPC option keep their network: the same resources, now counted.
moved {
  from = aws_vpc.main
  to   = aws_vpc.main[0]
}

moved {
  from = aws_internet_gateway.main
  to   = aws_internet_gateway.main[0]
}

moved {
  from = aws_route_table.public
  to   = aws_route_table.public[0]
}

moved {
  from = aws_route_table.private
  to   = aws_route_table.private[0]
}

moved {
  from = aws_vpc_endpoint.s3
  to   = aws_vpc_endpoint.s3[0]
}

moved {
  from = aws_vpc_endpoint.dynamodb
  to   = aws_vpc_endpoint.dynamodb[0]
}
