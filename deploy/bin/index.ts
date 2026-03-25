#!/usr/bin/env node
import 'source-map-support/register'
import * as cdk from 'aws-cdk-lib'

import { ParkAssistDatabaseStack } from '../lib/database'
import { ParkAssistGithubActionsRolesStack } from '../lib/github-actions-roles'
import { ParkAssistServiceStack } from '../lib/service'

const app = new cdk.App()

const serviceName = app.node.tryGetContext('serviceName') ?? process.env.SERVICE_NAME ?? 'parkassist'
const awsAccountId = app.node.tryGetContext('awsAccountId') ?? process.env.AWS_ACCOUNT_ID
const region = app.node.tryGetContext('region') ?? process.env.AWS_REGION ?? 'eu-west-1'
const environment = app.node.tryGetContext('environment') ?? process.env.APP_ENV ?? 'dev'
const repositoryFullName = app.node.tryGetContext('repositoryFullName') ?? process.env.GITHUB_REPOSITORY ?? 'amingrd/Parkassist'

if (!awsAccountId) {
  throw new Error('AWS_ACCOUNT_ID is required for deploy synthesis.')
}

const env = { account: awsAccountId, region }

const databaseStack = new ParkAssistDatabaseStack(app, 'ParkAssistDatabaseStack', {
  env,
  serviceName,
  environment,
})

new ParkAssistGithubActionsRolesStack(app, 'GithubActionsRolesStack', {
  env,
  serviceName,
  repositoryFullName,
})

const serviceStack = new ParkAssistServiceStack(app, 'ParkAssistServiceStack', {
  env,
  serviceName,
  environment,
  databaseSecretArnExportName: databaseStack.databaseSecretArnExportName,
  databaseSecurityGroupIdExportName: databaseStack.databaseSecurityGroupIdExportName,
})

serviceStack.addDependency(databaseStack)
