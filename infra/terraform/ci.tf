# GitHub Actions deploys by assuming a role with its own OIDC token: no AWS
# key exists in GitHub. Trust is narrowed to one workflow file on one branch
# of one repo. What the role grants is one thing, and it is not small: a
# shell on the box as root, through SSM's run-shell-script document. That is
# what a deploy is today (infra/deploy/deploy.sh), and it reaches everything
# on the box, /opt/hax/.env included. It cannot open an interactive session
# or touch AWS state, the database or the bucket directly. Narrowing it to a
# single custom SSM document that takes only a sha is the M3.5 upgrade.
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "deploy_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # A pull request, a tag or another branch presents a different subject
    # and is refused; a fork is a different repo.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/main"]
    }
    # And only this workflow file: another workflow on main (a schedule, a
    # manual dispatch) with id-token permission presents the same subject but
    # a different job_workflow_ref, and is refused.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:job_workflow_ref"
      values   = ["${var.github_repo}/.github/workflows/ci.yml@refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = "${var.project}-deploy"
  assume_role_policy = data.aws_iam_policy_document.deploy_assume.json
}

data "aws_iam_policy_document" "deploy" {
  # SendCommand authorizes on both the target instance and the document.
  statement {
    actions = ["ssm:SendCommand"]
    resources = [
      aws_instance.box.arn,
      "arn:aws:ssm:${var.region}::document/AWS-RunShellScript",
    ]
  }
  # Takes no resource-level permission; command ids are unguessable.
  statement {
    actions   = ["ssm:GetCommandInvocation"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "${var.project}-deploy"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}
