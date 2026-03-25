import * as cdk from 'aws-cdk-lib'
import type { Construct } from 'constructs'

import { GithubActionsBuildRole, GithubActionsDeployRole } from '@autoscout24/aws-cdk'

type GithubActionsRolesStackProps = cdk.StackProps & {
  serviceName: string
  repositoryFullName: string
}

export class ParkAssistGithubActionsRolesStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: GithubActionsRolesStackProps) {
    super(scope, id, props)

    new GithubActionsBuildRole(this, 'GithubActionsBuildRole', {
      repositoryName: props.repositoryFullName
    })

    new GithubActionsDeployRole(this, 'GithubActionsDeployRole', {
      repositoryName: props.repositoryFullName
    })
  }
}
