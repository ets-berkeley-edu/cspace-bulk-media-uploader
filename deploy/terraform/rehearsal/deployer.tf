# The deployer: a role with only the deployer policy, which ./bmu aws assumes for the rehearsal, so that every
# AccessDenied is the policy's. Only the administrator role that applies this configuration may assume it. Its name
# doesn't start with bmu-: the policy lets the deployer change bmu-* roles, and it mustn't be able to change its own.
# Sessions last an hour at most (assumed from an SSO session: role chaining), as rtl-BmuQaDeployer's.

data "aws_iam_session_context" "admin" {
  arn = data.aws_caller_identity.current.arn
}

resource "aws_iam_role" "deployer" {
  name                 = "${local.name}-deployer"
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = data.aws_iam_session_context.admin.issuer_arn }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "part" {
  count  = length(var.policy_parts)
  name   = "${local.name}-deployer-${count.index + 1}"
  policy = var.policy_parts[count.index]
}

resource "aws_iam_role_policy_attachment" "part" {
  count      = length(var.policy_parts)
  role       = aws_iam_role.deployer.name
  policy_arn = aws_iam_policy.part[count.index].arn
}
