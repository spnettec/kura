/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.util.*;import java.nio.file.*;import java.lang.reflect.*;
import org.eclipse.kura.KuraException;import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.configuration.ComponentConfiguration;import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.crypto.CryptoService;
import org.junit.jupiter.api.Test;import org.junit.jupiter.api.io.TempDir;
import org.osgi.service.cm.*;

class StartupPasswordConvergenceTest {
    @TempDir Path root;
    static CryptoService crypto() throws Exception {
        var crypto=mock(CryptoService.class);var sequence=new java.util.concurrent.atomic.AtomicInteger();
        when(crypto.encryptAes(any(char[].class))).thenAnswer(i->("aes"+sequence.incrementAndGet()+":"+new String((char[])i.getArgument(0))).toCharArray());
        when(crypto.decryptAes(any(char[].class))).thenAnswer(i->{String text=new String((char[])i.getArgument(0));if(text.isEmpty())return new char[0];if(!text.matches("aes[0-9]+:.*"))throw new KuraException(KuraErrorCode.DECODER_ERROR);return text.substring(text.indexOf(':')+1).toCharArray();});return crypto;
    }
    @Test void scalarArrayVectorAndListKeepExactStoredCiphertextsAndDetachedContainers() throws Exception {
        var crypto=crypto();Map<String,Object> logical=Map.of("p",new Password("secret"),"a",new Password[]{new Password(""),new Password("second")},
                "v",new Vector<>(List.of(new Password("third"))),"l",new ArrayList<>(List.of(new Password("fourth"))),"count",1);
        Map<String,Object> stored=Map.of("p","aes9:secret","a",new String[]{"aes8:","aes7:second"},"v",new Vector<>(List.of("aes6:third")),"l",new ArrayList<>(List.of("aes5:fourth")),"count",1);
        var result=StartupPasswordConvergence.preserve(logical,stored,crypto);
        assertEquals(stored.keySet(),result.keySet());for(String key:stored.keySet())assertTrue(ConfigurationRevision.sameValue(stored.get(key),result.get(key)));assertNotSame(stored.get("a"),result.get("a"));assertNotSame(stored.get("v"),result.get("v"));assertNotSame(stored.get("l"),result.get("l"));
        verify(crypto,never()).encryptAes(any(char[].class));assertTrue(Arrays.equals("secret".toCharArray(),((Password)logical.get("p")).getPassword()));
    }
    @Test void changedMissingUnauthenticatedOrWrongContainerPasswordsNeverConverge() throws Exception {
        var crypto=crypto();var logical=Map.<String,Object>of("p",new Password("secret"));
        for(var current:List.of(Map.<String,Object>of(),Map.<String,Object>of("p","aes1:changed"),Map.<String,Object>of("p","not-a-cipher"),Map.<String,Object>of("p",new String[]{"aes1:secret"}),Map.<String,Object>of("p","aes1:secret","service.factoryPid","other")))
            assertThrows(KuraException.class,()->StartupPasswordConvergence.preserve(logical,current,crypto));
        assertThrows(KuraException.class,()->StartupPasswordConvergence.preserve(logical,null,crypto));
        assertThrows(KuraException.class,()->StartupPasswordConvergence.preserve(Map.of("p",new Vector<>(List.of(new Password("secret")))),Map.of("p",Set.of("aes1:secret")),crypto));
        verify(crypto,never()).encryptAes(any(char[].class));
    }
    @Test void historicalVectorKeepsTheExactOrderedListReturnedByEquinox() throws Exception {
        var crypto = crypto();
        Map<String, Object> logical = Map.of("p", new Vector<>(List.of(new Password("first"), new Password("second"))));
        var admitted = new ArrayList<>(List.of("aes2:first", "aes1:second"));

        var preserved = StartupPasswordConvergence.preserve(logical, Map.of("p", admitted), crypto);

        var stored = assertInstanceOf(ArrayList.class, preserved.get("p"));
        assertEquals(admitted, stored);
        assertNotSame(admitted, stored);
        assertThrows(KuraException.class, () -> StartupPasswordConvergence.preserve(logical,
                Map.of("p", List.of("aes1:second", "aes2:first")), crypto));
        assertThrows(KuraException.class, () -> StartupPasswordConvergence.preserve(logical,
                Map.of("p", new String[] {"aes2:first", "aes1:second"}), crypto));
        verify(crypto, never()).encryptAes(any(char[].class));
    }
    static class Fixture extends ConfigurationServiceImpl {
        final List<ComponentConfiguration> values;
        Fixture(List<ComponentConfiguration> values){this.values=values;}
        @Override public Set<Long> getSnapshots(){return new TreeSet<>(Set.of(1L));}
        @Override XmlComponentConfigurations loadEncryptedSnapshotFileContent(long id){var xml=new XmlComponentConfigurations();xml.setPasswordEncoding(XmlComponentConfigurations.LOGICAL_PASSWORD_ENCODING);xml.setConfigurations(values);return xml;}
        void load() throws Exception {var method=ConfigurationServiceImpl.class.getDeclaredMethod("loadLatestSnapshotInConfigAdmin");method.setAccessible(true);try{method.invoke(this);}catch(InvocationTargetException e){if(e.getCause() instanceof Exception failure)throw failure;throw e;}}
    }
    ComponentConfiguration config(String pid){var c=new ComponentConfigurationImpl(pid,null,new HashMap<>(Map.of("kura.service.pid",pid,"secret",new Password("secret"))));c.setLogicalPasswords(true);return c;}
    Configuration cm(String pid,String cipher) throws Exception {var c=mock(Configuration.class);when(c.getPid()).thenReturn(pid);when(c.getProperties()).thenReturn(new Hashtable<>(Map.of("kura.service.pid",pid,"secret",cipher)));return c;}
    final class Admission implements AutoCloseable {
        final Field admission,completion;final Object oldAdmission,oldCompletion;final String property=System.getProperty(ControlledRecovery.REQUEST_PROPERTY);
        Admission(boolean normal)throws Exception {admission=ControlledRecovery.class.getDeclaredField("admission");completion=ControlledRecovery.class.getDeclaredField("completion");admission.setAccessible(true);completion.setAccessible(true);oldAdmission=admission.get(null);oldCompletion=completion.get(null);admission.set(null,null);completion.set(null,null);System.clearProperty(ControlledRecovery.REQUEST_PROPERTY);
            if(normal){Path snapshot=root.resolve("snapshot_1.xml");Files.writeString(snapshot,"owned snapshot");String sha=HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(snapshot)));System.setProperty(ControlledRecovery.REQUEST_PROPERTY,"owned-request");ControlledRecovery.admitNormalLoad("owned-request","owned-normal",snapshot,sha);}}
        public void close()throws Exception{admission.set(null,oldAdmission);completion.set(null,oldCompletion);if(property==null)System.clearProperty(ControlledRecovery.REQUEST_PROPERTY);else System.setProperty(ControlledRecovery.REQUEST_PROPERTY,property);}
    }
    @Test void guardedNormalStartupPreservesCipherBytesThroughTheActualCoreLoader() throws Exception {
        try(var ignored=new Admission(true)) {
            var admin=mock(ConfigurationAdmin.class);var c=cm("owned","aes9:secret");when(admin.listConfigurations(any())).thenReturn(new Configuration[]{c});when(admin.getConfiguration("owned","?")).thenReturn(c);
            var crypto=crypto();var core=new Fixture(List.of(config("owned")));core.setConfigurationAdmin(admin);core.setCryptoService(crypto);core.load();
            verify(c).updateIfDifferent(argThat(values->"aes9:secret".equals(values.get("secret"))));verify(crypto,never()).encryptAes(any(char[].class));
        }
    }
    @Test void mismatchingLaterPasswordStopsCoreBeforeAnyStartupCmDispatch() throws Exception {
        try(var ignored=new Admission(true)) {
            var admin=mock(ConfigurationAdmin.class);var first=cm("first","aes9:secret");var second=cm("second","aes8:changed");when(admin.listConfigurations(any())).thenReturn(new Configuration[]{first,second});
            var core=new Fixture(List.of(config("first"),config("second")));core.setConfigurationAdmin(admin);core.setCryptoService(crypto());assertThrows(KuraException.class,core::load);
            verify(admin,never()).getConfiguration(anyString(),anyString());verify(first,never()).updateIfDifferent(any());verify(second,never()).updateIfDifferent(any());
        }
    }
    @Test void ordinaryStartupKeepsItsIndependentEncryptionPath() throws Exception {
        try(var ignored=new Admission(false)) {
            var admin=mock(ConfigurationAdmin.class);var c=cm("owned","aes9:secret");when(admin.listConfigurations(any())).thenReturn(new Configuration[]{c});when(admin.getConfiguration("owned","?")).thenReturn(c);
            var crypto=crypto();var core=new Fixture(List.of(config("owned")));core.setConfigurationAdmin(admin);core.setCryptoService(crypto);core.load();
            verify(crypto).encryptAes(any(char[].class));verify(c).update(argThat(values->"aes1:secret".equals(values.get("secret"))));
        }
    }
}
