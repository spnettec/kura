/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.tools.recovery;

import static org.junit.jupiter.api.Assertions.*;
import java.net.JarURLConnection;
import java.util.*;
import java.nio.file.Path;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.core.configuration.ConfigurationRestore;
import org.eclipse.kura.core.crypto.CryptoServiceImpl;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.osgi.framework.*;
import org.osgi.framework.launch.*;
import org.osgi.service.cm.*;

/** Real API/persistence contract only; this harness loads CM, no Kura business bundles or DS. */
class ConfigurationRestoreEquinoxTest {
    @TempDir Path directory;
    Framework framework;
    ConfigurationAdmin admin;
    void open() throws Exception {
        framework=ServiceLoader.load(FrameworkFactory.class).findFirst().orElseThrow().newFramework(Map.of(
                Constants.FRAMEWORK_STORAGE,directory.resolve("framework").toString(),
                Constants.FRAMEWORK_SYSTEMPACKAGES_EXTRA,"org.osgi.service.cm;version=1.6.1,org.osgi.service.log;version=1.5.0,org.osgi.service.coordinator;version=1.0.2"));
        framework.init();framework.start();
        Bundle cm=Arrays.stream(framework.getBundleContext().getBundles()).filter(b->"org.eclipse.equinox.cm".equals(b.getSymbolicName())).findFirst().orElse(null);
        if(cm==null){
            var resource=getClass().getClassLoader().getResource("org/eclipse/equinox/internal/cm/Activator.class");
            String jar=((JarURLConnection)resource.openConnection()).getJarFileURL().toString();
            cm=framework.getBundleContext().installBundle(jar);
        }
        cm.start();
        for(int i=0;i<100;i++){
            var reference=framework.getBundleContext().getServiceReference(ConfigurationAdmin.class);
            if(reference!=null){admin=framework.getBundleContext().getService(reference);break;}
            Thread.sleep(10);
        }
        assertNotNull(admin);
        assertFalse(Arrays.stream(framework.getBundleContext().getBundles()).anyMatch(b->"org.apache.felix.scr".equals(b.getSymbolicName())));
    }
    void close() throws Exception {if(framework!=null){framework.stop();assertNotEquals(FrameworkEvent.WAIT_TIMEDOUT,framework.waitForStop(5000).getType());}}
    ComponentConfiguration config(String pid,String factory,Map<String,Object> props) {
        Map<String,Object> values=new HashMap<>(props);values.put("kura.service.pid",pid);if(factory!=null){values.put("service.factoryPid",factory);}
        return new ComponentConfigurationImpl(pid,null,values);
    }
    @Test void realConfigAdminFullReplacementAndFactoryRemovalSurviveFrameworkRestart() throws Exception {
        open();
        List<ComponentConfiguration> target;
        String retainedPid;
        try {
            Configuration old=admin.getConfiguration("single","?");old.update(new Hashtable<>(Map.of("kura.service.pid","single","count",1,"stale",true)));
            Configuration absent=admin.createFactoryConfiguration("fixture.factory","?");absent.update(new Hashtable<>(Map.of("kura.service.pid","absent","count",0)));
            Configuration kept=admin.createFactoryConfiguration("fixture.factory","?");kept.update(new Hashtable<>(Map.of("kura.service.pid","retained","count",1)));retainedPid=kept.getPid();
            Configuration foreign=admin.getConfiguration("foreign","?");foreign.update(new Hashtable<>(Map.of("untouched","yes")));
            var crypto=CryptoServiceImpl.forSnapshotRecovery(null,true);
            target=List.of(config("single",null,Map.of("count",2,"labels",new String[]{"a","b"},"enabled",true)),
                    config("retained","fixture.factory",Map.of("count",3,"password",new Password(crypto.encryptAes("canary".toCharArray())))),
                    config("new","fixture.factory",Map.of("value",2.5)));
            var applied=ConfigurationRestore.apply(admin,target,backup->{assertEquals(3,backup.size());assertEquals(1,old.getProperties().get("count"));});
            assertEquals(List.of("absent"),applied.deleted());assertEquals(retainedPid,kept.getPid());
            assertEquals("yes",foreign.getProperties().get("untouched"));assertNull(old.getProperties().get("stale"));
            ConfigurationRestore.verify(admin,target);
        } finally {close();}
        open();
        try {
            ConfigurationRestore.verify(admin,target);
            assertNull(admin.listConfigurations("(kura.service.pid=absent)"));
            Configuration[] retained=admin.listConfigurations("(kura.service.pid=retained)");assertEquals(1,retained.length);assertEquals(retainedPid,retained[0].getPid());
            assertEquals("yes",admin.getConfiguration("foreign","?").getProperties().get("untouched"));
        } finally {close();}
    }
    @Test void inverseApiRestoreSurvivesRestartAndPreservesEncryptedSecretsAndUnmanagedRecords() throws Exception {
        open();List<ComponentConfiguration> original;
        try {
            var crypto=CryptoServiceImpl.forSnapshotRecovery(null,true);
            String secret=new String(crypto.encryptAes("old-canary".toCharArray()));
            Configuration old=admin.getConfiguration("single","?");old.update(new Hashtable<>(Map.of("kura.service.pid","single","count",9,"stale",true,"password",secret)));
            Configuration gone=admin.createFactoryConfiguration("old.factory","?");gone.update(new Hashtable<>(Map.of("kura.service.pid","gone","count",9)));
            admin.getConfiguration("foreign","?").update(new Hashtable<>(Map.of("owner","other")));
            original=ConfigurationRestore.capture(admin);
            var next=List.of(config("single",null,Map.of("count",2)),config("new","factory",Map.of("count",2)));
            ConfigurationRestore.apply(admin,next,ignored->{});
            // Simulate an interrupted inverse: current records can be wholly old or new.
            old.update(new Hashtable<>(original.stream().filter(c->c.getPid().equals("single")).findFirst().orElseThrow().getConfigurationProperties()));
            ConfigurationRestore.compensate(admin,original,ConfigurationRestore.expected(next),backup->assertEquals(2,backup.size()));
            ConfigurationRestore.verify(admin,original);
            assertArrayEquals("old-canary".toCharArray(),crypto.decryptAes(((String)old.getProperties().get("password")).toCharArray()));
        } finally {close();}
        open();try {ConfigurationRestore.verify(admin,original);assertNull(admin.listConfigurations("(kura.service.pid=new)"));assertEquals("other",admin.getConfiguration("foreign","?").getProperties().get("owner"));}finally{close();}
    }
    @Test void emptyOriginalCompensationDeletesOnlyNewManagedRecordsAndPersistsEmptySet() throws Exception {
        open();try {
            admin.getConfiguration("foreign","?").update(new Hashtable<>(Map.of("owner","other")));
            var next=List.of(config("new","factory",Map.of("count",2)));
            ConfigurationRestore.apply(admin,next,ignored->{});
            ConfigurationRestore.compensate(admin,List.of(),next,backup->assertEquals(1,backup.size()));
            assertTrue(ConfigurationRestore.capture(admin).isEmpty());
        } finally {close();}
        open();try{assertTrue(ConfigurationRestore.capture(admin).isEmpty());assertEquals("other",admin.getConfiguration("foreign","?").getProperties().get("owner"));}finally{close();}
    }

    @Test void typedContainersAndPasswordCollectionsSurviveXmlCmRestartAndInverse() throws Exception {
        var crypto=CryptoServiceImpl.forSnapshotRecovery(null,true);
        Map<String,Object> values=new LinkedHashMap<>();
        values.put("ints",new int[]{-3,4});values.put("empty",new byte[0]);
        values.put("chars",new char[]{'中','x'});values.put("boxedEmpty",new Integer[0]);
        values.put("vector",new Vector<>(List.of("a","b","a")));values.put("emptyVector",new Vector<>());
        values.put("list",new ArrayList<>(List.of(3L,4L,3L)));values.put("emptyList",new ArrayList<>());
        var secrets=new Vector<Password>();
        secrets.add(new Password(crypto.encryptAes("container-secret-a".toCharArray())));
        secrets.add(new Password(crypto.encryptAes("container-secret-b".toCharArray())));
        values.put("secrets",secrets);
        var xml=new org.eclipse.kura.core.configuration.XmlComponentConfigurations();
        xml.setConfigurations(List.of(config("containers",null,values)));
        var bytes=new java.io.ByteArrayOutputStream();
        new org.eclipse.kura.internal.xml.marshaller.unmarshaller.XmlJavaComponentConfigurationsMapper(crypto).marshal(bytes,xml);
        assertFalse(bytes.toString(java.nio.charset.StandardCharsets.UTF_8).contains("container-secret"));
        var target=SnapshotTool.decode(bytes.toByteArray(),crypto,"authenticated").configurations();
        List<ComponentConfiguration> original;
        open();try {
            admin.getConfiguration("containers","?").update(new Hashtable<>(Map.of("kura.service.pid","containers","old",true)));
            admin.getConfiguration("foreign","?").update(new Hashtable<>(Map.of("owner","other")));
            original=ConfigurationRestore.capture(admin);
            ConfigurationRestore.apply(admin,target,backup->assertEquals(1,backup.size()));
            var applied=admin.getConfiguration("containers","?").getProperties();
            assertArrayEquals(new int[]{-3,4},(int[])applied.get("ints"));
            assertEquals(0,((byte[])applied.get("empty")).length);
            assertEquals(new Vector<>(),applied.get("emptyVector"));
            var stored=(Collection<?>)applied.get("secrets");
            assertEquals(2,stored.size());assertTrue(stored.stream().allMatch(String.class::isInstance));
            assertArrayEquals("container-secret-a".toCharArray(),crypto.decryptAes(stored.iterator().next().toString().toCharArray()));
        }finally{close();}
        open();try {
            ConfigurationRestore.verify(admin,target);
            ConfigurationRestore.compensate(admin,original,ConfigurationRestore.expected(target),backup->assertEquals(1,backup.size()));
            ConfigurationRestore.verify(admin,original);
            assertNull(admin.getConfiguration("containers","?").getProperties().get("ints"));
            assertEquals("other",admin.getConfiguration("foreign","?").getProperties().get("owner"));
        }finally{close();}
    }

}
