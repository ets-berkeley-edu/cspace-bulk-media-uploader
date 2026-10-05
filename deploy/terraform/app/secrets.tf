# The read-only CollectionSpace account that checks an intern's drafts (design: Roles, The read-only service
# account; backend/bmu/reader.py). Terraform creates the secret empty. Its value, {"username": "...", "password":
# "..."}, is set by hand with the AWS CLI (deploy/README.md), so the password is never in the code, in a settings
# file or in Terraform's state. Until it is set, an intern's checks answer that the account isn't ready.
resource "aws_secretsmanager_secret" "reader" {
  name        = "${local.name}/cspace-reader"
  description = "BMU: the read-only CollectionSpace account (role BMU_Reader) used only for interns' checks."

  # An environment whose data matters keeps a deleted secret for 30 days; a trial environment's goes at once, so
  # the environment can be destroyed and created again under the same name.
  recovery_window_in_days = var.protect_data ? 30 : 0
}
