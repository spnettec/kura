/* Copyright (c) 2026 YOFC. SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.util.*;
import org.eclipse.kura.configuration.ConfigurationRevisionService;
import org.eclipse.kura.configuration.Password;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.parallel.ResourceLock;
import org.junit.jupiter.api.parallel.Resources;
import org.osgi.service.cm.Configuration;
import org.osgi.service.cm.ConfigurationAdmin;

/** Real Core stored reader,isolated CM and manually seeded registration metadata. */
@ResourceLock(Resources.SYSTEM_PROPERTIES)
class StoredConfigurationViewTest {
    private static final String V4="org.eclipse.kura.net.admin.FirewallConfigurationService";
    private static final String V6="org.eclipse.kura.net.admin.ipv6.FirewallConfigurationServiceIPv6";
    private static final Set<String> PIDS=Set.of(V4,V6);
    private ConfigurationServiceImpl core;
    private ConfigurationAdmin admin;
    private String previous;
    private final Map<String,Configuration> configurations=new HashMap<>();
    private final Map<String,Dictionary<String,Object>> dictionaries=new HashMap<>();

    @SuppressWarnings("unchecked") private <T> T field(String name) throws Exception {
        var field=ConfigurationServiceImpl.class.getDeclaredField(name);field.setAccessible(true);return (T)field.get(core);
    }
    @BeforeEach void setup() throws Exception {
        previous=System.getProperty(ExternalConfigurations.RESERVED_PIDS_PROPERTY);
        System.clearProperty(ExternalConfigurations.RESERVED_PIDS_PROPERTY);
        core=new ConfigurationServiceImpl();admin=mock(ConfigurationAdmin.class);core.setConfigurationAdmin(admin);
        for(String pid:PIDS) {
            this.<Map<String,String>>field("servicePidByPid").put(pid,pid);
            this.<Set<String>>field("allActivatedPids").add(pid);
            var configuration=mock(Configuration.class);when(configuration.getPid()).thenReturn(pid);
            when(configuration.getChangeCount()).thenReturn(3L);
            Dictionary<String,Object> dictionary=new Hashtable<>();dictionary.put("service.pid",pid);
            dictionary.put("rule",new String[]{"retained"});when(configuration.getProperties()).thenReturn(dictionary);
            configurations.put(pid,configuration);dictionaries.put(pid,dictionary);
            when(admin.listConfigurations("(service.pid="+pid+")")).thenReturn(new Configuration[]{configuration});
        }
    }
    @AfterEach void restore() {
        if(previous==null)System.clearProperty(ExternalConfigurations.RESERVED_PIDS_PROPERTY);
        else System.setProperty(ExternalConfigurations.RESERVED_PIDS_PROPERTY,previous);
    }
    private void rejected(ConfigurationRevisionService.Reason reason,Set<String> pids) {
        var error=assertThrows(ConfigurationRevisionService.Rejected.class,()->core.readStoredRevisionViews(pids));
        assertEquals(reason,error.getReason());
    }
    @Test void actualStoredValuesAreDetachedWithoutCallingAComponentOrCreatingCm() throws Exception {
        core=spy(core);
        doThrow(new AssertionError("stored reads must not call a component-owned getter"))
                .when(core).getComponentConfiguration(anyString());
        var result=core.readStoredRevisionViews(PIDS);assertEquals(PIDS,result.keySet());
        assertThrows(UnsupportedOperationException.class,result::clear);
        for(String pid:PIDS) {
            var view=result.get(pid);assertTrue(view.present());assertEquals(pid,view.configuration().getPid());
            assertTrue(view.revision().startsWith("stored:"));
            var detached=(String[])view.configuration().getConfigurationProperties().get("rule");
            detached[0]="caller edit";assertEquals("retained",((String[])dictionaries.get(pid).get("rule"))[0]);
            assertFalse(view.toString().contains("caller edit"));
            verify(configurations.get(pid),never()).update(any());verify(configurations.get(pid),never()).delete();
        }
        verify(core,never()).getComponentConfiguration(anyString());
        verify(admin,times(4)).listConfigurations(anyString());verifyNoMoreInteractions(admin);
    }
    @Test void absentCmIsExplicitAndNeverCreatedOrSeeded() throws Exception {
        when(admin.listConfigurations("(service.pid="+V4+")")).thenReturn(null);
        var view=core.readStoredRevisionViews(Set.of(V4)).get(V4);
        assertFalse(view.present());assertTrue(view.configuration().getConfigurationProperties().isEmpty());
        verify(admin,times(2)).listConfigurations(anyString());verifyNoMoreInteractions(admin);
    }
    @Test void countChangeWithinOneReadRefusesBeforeAnyResult() {
        when(configurations.get(V4).getChangeCount()).thenReturn(3L,4L);
        rejected(ConfigurationRevisionService.Reason.CONFLICT,PIDS);
    }
    @Test void countAbaBetweenTheTwoCohortPassesIsNotHiddenBySameValues() {
        when(configurations.get(V4).getChangeCount()).thenReturn(3L,3L,5L,5L);
        rejected(ConfigurationRevisionService.Reason.CONFLICT,PIDS);
    }
    @Test void changedValuesWithoutReportedCountStillRefuse() {
        Dictionary<String,Object> later=new Hashtable<>();later.put("service.pid",V4);later.put("rule",new String[]{"changed"});
        when(configurations.get(V4).getProperties()).thenReturn(dictionaries.get(V4),later);
        rejected(ConfigurationRevisionService.Reason.CONFLICT,PIDS);
    }
    @Test void malformedAllRequestsRefuseBeforeCmCallbacks() {
        for(Set<String> input:Arrays.<Set<String>>asList(null,Set.of(),Collections.singleton(null),Set.of("bad\n"),Set.of("x".repeat(513)))) {
            rejected(ConfigurationRevisionService.Reason.INVALID_ARGUMENT,input);
        }
        verifyNoInteractions(admin);
    }
    @Test void unknownFactoryAliasAndUnsettledPidsCannotAcquireStoredAuthority() throws Exception {
        rejected(ConfigurationRevisionService.Reason.UNSUPPORTED,Set.of("unregistered"));
        this.<Map<String,String>>field("factoryPidByPid").put(V4,"factory");
        rejected(ConfigurationRevisionService.Reason.UNSUPPORTED,PIDS);this.<Map<String,String>>field("factoryPidByPid").clear();
        this.<Map<String,String>>field("servicePidByPid").put(V4,"different.physical.pid");
        rejected(ConfigurationRevisionService.Reason.UNSUPPORTED,PIDS);this.<Map<String,String>>field("servicePidByPid").put(V4,V4);
        this.<Set<String>>field("revisionUncertain").add(V4);rejected(ConfigurationRevisionService.Reason.CONFLICT,PIDS);
        verifyNoInteractions(admin);
    }
    @Test void startupReservedOwnerNeverFallsBackToStoredCm() throws Exception {
        System.setProperty(ExternalConfigurations.RESERVED_PIDS_PROPERTY,V4);core=new ConfigurationServiceImpl();core.setConfigurationAdmin(admin);
        this.<Map<String,String>>field("servicePidByPid").put(V4,V4);this.<Set<String>>field("allActivatedPids").add(V4);
        rejected(ConfigurationRevisionService.Reason.UNSUPPORTED,Set.of(V4));verifyNoInteractions(admin);
    }
    @Test void duplicateOrWrongPhysicalCmEntriesRefuse() throws Exception {
        when(admin.listConfigurations("(service.pid="+V4+")")).thenReturn(new Configuration[]{configurations.get(V4),configurations.get(V4)});
        rejected(ConfigurationRevisionService.Reason.CONFLICT,Set.of(V4));
        when(admin.listConfigurations("(service.pid="+V4+")")).thenReturn(new Configuration[]{configurations.get(V6)});
        rejected(ConfigurationRevisionService.Reason.CONFLICT,Set.of(V4));
    }
    @Test void storagePasswordRepresentationIsNotGuessedOrDecodedAndOldProvidersReject() throws Exception {
        var password=new Password("logical-looking-storage-prefix".toCharArray());dictionaries.get(V4).put("secret",password);
        var result=core.readStoredRevisionViews(Set.of(V4)).get(V4);
        assertArrayEquals(password.getPassword(),((Password)result.configuration().getConfigurationProperties().get("secret")).getPassword());
        assertNotSame(password,result.configuration().getConfigurationProperties().get("secret"));
        var older=mock(ConfigurationRevisionService.class,CALLS_REAL_METHODS);
        var error=assertThrows(ConfigurationRevisionService.Rejected.class,()->older.readStoredRevisionViews(PIDS));
        assertEquals(ConfigurationRevisionService.Reason.UNSUPPORTED,error.getReason());
    }
}
