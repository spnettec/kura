// A dedicated, prepared multi-repository agent workspace is required.
// See docs/migration/ci-migration.md; Maven/JDK come from the agent environment.
node(env.KURA_CI_AGENT_LABEL ?: '') {
    properties([
        disableConcurrentBuilds(),
        buildDiscarder(logRotator(numToKeepStr: '10', artifactNumToKeepStr: '3'))
    ])
    stage('Checkout core') {
        dir('kura') { checkout scm }
    }
    stage('Check toolchain and workspace') {
        sh 'bash kura/tools/ci/verify-workspace.sh --check'
    }
    try {
        stage('Maven bundles and JUnit 5') {
            timeout(time: 3, unit: 'HOURS') {
                sh 'bash kura/tools/ci/verify-workspace.sh'
            }
        }
    } finally {
        stage('Publish current test reports') {
            junit testResults: 'kura/target/ci/test-reports/**/TEST-*.xml', allowEmptyResults: false
            archiveArtifacts artifacts: 'kura/target/ci/summary.json', allowEmptyArchive: false
        }
    }
    stage('Archive distributions') {
        archiveArtifacts artifacts: '**/target/**/*.deb,**/target/**/*.dp', allowEmptyArchive: false
    }
}
