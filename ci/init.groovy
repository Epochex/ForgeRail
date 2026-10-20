import jenkins.model.Jenkins
import hudson.security.*
import hudson.security.csrf.DefaultCrumbIssuer
import hudson.slaves.*
import hudson.model.Node
import hudson.model.BooleanParameterDefinition
import hudson.model.ParametersDefinitionProperty
import org.jenkinsci.plugins.workflow.job.WorkflowJob
import org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition

def j = Jenkins.get()
j.setNumExecutors(0)
def realm = new HudsonPrivateSecurityRealm(false)
realm.createAccount('labadmin', System.getenv('JENKINS_PASSWORD'))
j.setSecurityRealm(realm)
def auth = new FullControlOnceLoggedInAuthorizationStrategy()
auth.setAllowAnonymousRead(false)
j.setAuthorizationStrategy(auth)
j.setCrumbIssuer(new DefaultCrumbIssuer(true))
if (j.getNode('linux-lab') == null) {
  def agent = new DumbSlave('linux-lab','Separate Linux Python agent','/home/agent','1',Node.Mode.EXCLUSIVE,'linux-lab',new JNLPLauncher(),new RetentionStrategy.Always(),[])
  j.addNode(agent)
}
def secretFile = new File('/shared/agent-secret')
secretFile.text = j.getComputer('linux-lab').getJnlpMac()
secretFile.setReadable(false, false); secretFile.setReadable(true, true)
def job = j.getItem('gamebuild-lab') ?: j.createProject(WorkflowJob, 'gamebuild-lab')
job.addProperty(new ParametersDefinitionProperty(new BooleanParameterDefinition('RUN_UNITY',true,'Build a real Unity Windows Player')))
job.setDefinition(new CpsFlowDefinition(new File('/workspace/ci/Jenkinsfile').text, true))
job.save(); j.save()
