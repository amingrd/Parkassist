import * as cdk from 'aws-cdk-lib'
import type { Construct } from 'constructs'

// These imports follow the platform guidance shared by the team and may need
// small alignment against the current as24 template version when this is wired
// into the target AWS account.
import { AuroraDatabase, AuroraEngineType } from '@autoscout24/aws-cdk'

type DatabaseStackProps = cdk.StackProps & {
  serviceName: string
  environment: string
}

export class ParkAssistDatabaseStack extends cdk.Stack {
  public readonly databaseSecretArnExportName: string
  public readonly databaseSecurityGroupIdExportName: string

  constructor(scope: Construct, id: string, props: DatabaseStackProps) {
    super(scope, id, props)

    const database = new AuroraDatabase(this, 'ParkAssistAurora', {
      serviceName: props.serviceName,
      engineType: AuroraEngineType.POSTGRESQL,
      publiclyAccessible: false,
      region: props.env?.region ?? 'eu-west-1',
      masterPassword: cdk.SecretValue.ssmSecure(`/${props.serviceName}/${props.environment}/db/masterPassword`),
      networkType: 'PRIVATE_WITH_EGRESS',
      databaseName: 'parkassist',
      instanceCount: 1
    })

    this.databaseSecretArnExportName = `${props.serviceName}-${props.environment}-db-secret-arn`
    this.databaseSecurityGroupIdExportName = `${props.serviceName}-${props.environment}-db-sg-id`

    new cdk.CfnOutput(this, 'DatabaseSecretArn', {
      value: database.secret?.secretArn ?? '',
      exportName: this.databaseSecretArnExportName
    })

    new cdk.CfnOutput(this, 'DatabaseSecurityGroupId', {
      value: database.securityGroup.securityGroupId,
      exportName: this.databaseSecurityGroupIdExportName
    })
  }
}
