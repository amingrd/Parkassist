import * as cdk from 'aws-cdk-lib'
import { PolicyStatement } from 'aws-cdk-lib/aws-iam'
import { SecurityGroup, Port, Peer, Vpc } from 'aws-cdk-lib/aws-ec2'
import { Repository } from 'aws-cdk-lib/aws-ecr'
import type { Construct } from 'constructs'

import { InfinityServiceCustomResource } from '@autoscout24/aws-cdk'

type ServiceStackProps = cdk.StackProps & {
  serviceName: string
  environment: string
  databaseSecretArnExportName: string
  databaseSecurityGroupIdExportName: string
}

export class ParkAssistServiceStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ServiceStackProps) {
    super(scope, id, props)

    const imageTag = this.node.tryGetContext('imageTag') ?? process.env.IMAGE_TAG ?? 'local-dev'
    const accountId = props.env?.account ?? process.env.AWS_ACCOUNT_ID ?? ''
    const region = props.env?.region ?? process.env.AWS_REGION ?? 'eu-west-1'
    const vpc = Vpc.fromLookup(this, 'SharedVpc', { vpcName: 'shared-vpc' })
    const repository = Repository.fromRepositoryName(this, 'Repository', props.serviceName)
    const databaseSecurityGroup = SecurityGroup.fromSecurityGroupId(
      this,
      'DatabaseSecurityGroup',
      cdk.Fn.importValue(props.databaseSecurityGroupIdExportName)
    )

    const service = new InfinityServiceCustomResource(this, 'InfinityService', {
      serviceName: props.serviceName,
      image: `${accountId}.dkr.ecr.${region}.amazonaws.com/${repository.repositoryName}:${imageTag}`,
      containerPort: 8000,
      loadBalancerExposure: 'internal',
      cpuArchitecture: 'arm64',
      cpu: 256,
      memory: 256,
      minCapacity: props.environment === 'prod' ? 2 : 1,
      maxCapacity: 20,
      cpuScalingThreshold: 75,
      slowStart: 'Disabled',
      containerEnvironment: {
        APP_ENV: props.environment,
        AUTH_MODE: 'okta',
        AWS_REGION: region,
        BASE_URL: `https://${props.serviceName}.internal`,
        HOST: '0.0.0.0',
        PORT: '8000',
        DATABASE_SECRET_ID: `/${props.serviceName}/${props.environment}/db`,
        SESSION_SECRET_PARAMETER: `/${props.serviceName}/${props.environment}/sessionSecret`,
        OKTA_ISSUER: '/parkassist/fill-me',
        OKTA_CLIENT_ID: '/parkassist/fill-me',
        OKTA_CLIENT_SECRET_PARAMETER: `/${props.serviceName}/${props.environment}/oktaClientSecret`,
        SLACK_WEBHOOK_URL_PARAMETER: `/${props.serviceName}/${props.environment}/slackWebhookUrl`,
        PARKING_GUIDE_URL: 'https://replace-with-internal-guide-url',
        BOOTSTRAP_ADMIN_EMAILS: 'replace-with-admin@leasingmarkt.de'
      },
      healthCheckProbes: {
        livenessProbe: {
          type: 'http',
          httpPath: '/health/liveness',
          initialDelaySeconds: 10,
          periodSeconds: 15,
          timeoutSeconds: 5,
          failureThreshold: 5
        },
        readinessProbe: {
          type: 'http',
          httpPath: '/health/readiness',
          initialDelaySeconds: 15,
          periodSeconds: 10,
          timeoutSeconds: 5,
          failureThreshold: 3
        }
      },
      metadata: {
        datadogDashboardId: 'replace-with-dashboard-id'
      }
    })

    service.role.addToPolicy(
      new PolicyStatement({
        actions: ['ssm:DescribeParameters'],
        resources: ['*']
      })
    )

    service.role.addToPolicy(
      new PolicyStatement({
        actions: ['ssm:GetParameters'],
        resources: [
          `arn:aws:ssm:${region}:${accountId}:parameter/${props.serviceName}/*`
        ]
      })
    )

    service.role.addToPolicy(
      new PolicyStatement({
        actions: ['kms:Decrypt'],
        resources: [`arn:aws:kms:${region}:${accountId}:alias/aws/ssm`]
      })
    )

    service.role.addToPolicy(
      new PolicyStatement({
        actions: ['secretsmanager:GetSecretValue'],
        resources: [cdk.Fn.importValue(props.databaseSecretArnExportName)]
      })
    )

    databaseSecurityGroup.addIngressRule(Peer.ipv4('10.144.0.0/12'), Port.tcp(5432), 'Allow Infinity workloads to reach Aurora')

    new cdk.CfnOutput(this, 'InternalServiceMode', {
      value: 'Infinity internal service configured'
    })

    // Keep a VPC lookup in this stack so the service is synthesized against the
    // shared-vpc paved path and can be refined with template-specific settings.
    new cdk.CfnOutput(this, 'VpcId', { value: vpc.vpcId })
  }
}
