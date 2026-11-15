/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.lang.reflect.Field;
import java.util.*;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.core.configuration.metatype.*;
import org.junit.jupiter.api.Test;
import org.osgi.framework.Bundle;
import org.osgi.service.cm.Configuration;
import org.osgi.service.cm.ConfigurationAdmin;

class MetadataRefreshTest {
    void field(Object target,String name,Object value) throws Exception {Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);f.set(target,value);}
    Map<String,Tocd> definitions(ConfigurationServiceImpl service) throws Exception {Field f=service.getClass().getDeclaredField("ocds");f.setAccessible(true);return (Map<String,Tocd>)f.get(service);}
    Tocd definition(String id,String defaultValue) {var definition=new Tocd();definition.setId(id);var count=new Tad();count.setId("count");count.setType(Tscalar.INTEGER);count.setCardinality(0);count.setDefault(defaultValue);definition.addAD(count);return definition;}
    @Test void refreshAndUnregisterKeepExistingCmValuesAndRemoveTheMetadata() throws Exception {
        var service=new ConfigurationServiceImpl();var admin=mock(ConfigurationAdmin.class);var cm=mock(Configuration.class);var bundle=mock(Bundle.class);
        field(service,"configurationAdmin",admin);var properties=new Hashtable<String,Object>();properties.put(ConfigurationService.KURA_SERVICE_PID,"fixture");properties.put("count",7);
        when(admin.getConfiguration("fixture","?")).thenReturn(cm);when(cm.getProperties()).thenReturn(properties);
        service.replaceBundleMetadata(bundle,Map.of("fixture",new MetadataDefinition(definition("first","1"),false)));
        service.replaceBundleMetadata(bundle,Map.of("fixture",new MetadataDefinition(definition("second","9"),false)));
        assertEquals("second",definitions(service).get("fixture").getId());assertEquals(7,properties.get("count"));
        verify(cm,never()).update(any());verify(cm,never()).updateIfDifferent(any());service.onBundleRemoved(bundle);assertFalse(definitions(service).containsKey("fixture"));assertEquals(7,properties.get("count"));
    }
    @Test void controlledRecoveryRegistersReadMetadataWithoutCreatingOrChangingCm() throws Exception {
        String old=System.getProperty(ControlledRecovery.REQUEST_PROPERTY);System.setProperty(ControlledRecovery.REQUEST_PROPERTY,"owned-unit-only-request");
        try {
            var service=new ConfigurationServiceImpl();var admin=mock(ConfigurationAdmin.class);field(service,"configurationAdmin",admin);var bundle=mock(Bundle.class);
            service.replaceBundleMetadata(bundle,Map.of("fixture",new MetadataDefinition(definition("during-recovery","9"),false)));
            assertEquals("during-recovery",definitions(service).get("fixture").getId());verifyNoInteractions(admin);
        } finally {if(old==null){System.clearProperty(ControlledRecovery.REQUEST_PROPERTY);}else{System.setProperty(ControlledRecovery.REQUEST_PROPERTY,old);}}
    }
    @Test void duplicateBundleOwnersCannotLeaveAnArbitraryOcdAndRemovalRestoresTheRemainingOwner() throws Exception {
        var service=new ConfigurationServiceImpl();var admin=mock(ConfigurationAdmin.class);field(service,"configurationAdmin",admin);var cm=mock(Configuration.class);
        var properties=new Hashtable<String,Object>();properties.put(ConfigurationService.KURA_SERVICE_PID,"fixture");properties.put("count",7);when(admin.getConfiguration("fixture","?")).thenReturn(cm);when(cm.getProperties()).thenReturn(properties);
        var first=mock(Bundle.class);var second=mock(Bundle.class);
        service.replaceBundleMetadata(first,Map.of("fixture",new MetadataDefinition(definition("first","1"),false)));
        service.replaceBundleMetadata(second,Map.of("fixture",new MetadataDefinition(definition("second","2"),false)));assertFalse(definitions(service).containsKey("fixture"));
        service.onBundleRemoved(second);assertEquals("first",definitions(service).get("fixture").getId());verify(cm,never()).update(any());verify(cm,never()).updateIfDifferent(any());
    }

    @Test void metadataRemovalRetainsPasswordClassificationForExistingFactoryInstances() throws Exception {
        var service=new ConfigurationServiceImpl();var admin=mock(ConfigurationAdmin.class);field(service,"configurationAdmin",admin);
        Field mapping=ConfigurationServiceImpl.class.getDeclaredField("servicePidByPid");mapping.setAccessible(true);((Map<String,String>)mapping.get(service)).put("instance","cm.instance");
        mapping=ConfigurationServiceImpl.class.getDeclaredField("factoryPidByPid");mapping.setAccessible(true);((Map<String,String>)mapping.get(service)).put("instance","fixture.factory");
        var cm=mock(Configuration.class);when(admin.getConfiguration("cm.instance","?")).thenReturn(cm);var props=new Hashtable<String,Object>();props.put(ConfigurationService.KURA_SERVICE_PID,"instance");props.put("opaque",new Vector<>(List.of("encrypted-placeholder")));when(cm.getProperties()).thenReturn(props);
        var definition=new Tocd();definition.setId("private.definition");var secret=new Tad();secret.setId("opaque");secret.setType(Tscalar.PASSWORD);secret.setCardinality(-4);secret.setRequired(false);definition.addAD(secret);
        var owner=mock(Bundle.class);service.replaceBundleMetadata(owner,Map.of("fixture.factory",new MetadataDefinition(definition,true)));service.onBundleRemoved(owner);
        Field names=ConfigurationServiceImpl.class.getDeclaredField("passwordPropertiesByPid");names.setAccessible(true);assertTrue(((Map<String,Set<String>>)names.get(service)).get("instance").contains("opaque"));verify(cm,never()).update(any());verify(cm,never()).updateIfDifferent(any());
    }
}
