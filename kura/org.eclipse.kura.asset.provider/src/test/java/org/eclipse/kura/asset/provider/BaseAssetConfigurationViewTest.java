package org.eclipse.kura.asset.provider;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.util.*;
import org.eclipse.kura.internal.asset.provider.BaseAssetConfiguration;
import org.junit.jupiter.api.Test;

class BaseAssetConfigurationViewTest {
    @Test void nativeConfigurationViewExcludesRegistrationPropertiesAndRetainsBusinessIdentity() throws Exception {
        Map<String,Object> supplied=new HashMap<>(Map.of("kura.service.pid","owned.asset","service.pid","owned.cm",
                "service.factoryPid","org.eclipse.kura.wire.WireAsset","driver.pid","owned.driver",
                "request.timeout",10,"temperature#component.id",99,"temperature#+enabled",true));
        var runtime=List.of("component.id","component.name","service.id","service.bundleid","service.scope",
                "service.bundleLocation","objectClass","osgi.ds.satisfying.condition.target",
                "kura.ui.service.hide","kura.ui.toolsSorted");
        for(String name:runtime)supplied.put(name,"registration-only");
        var config=mock(BaseAssetConfiguration.class);when(config.getProperties()).thenReturn(supplied);
        var asset=new BaseAsset();var field=BaseAsset.class.getDeclaredField("config");field.setAccessible(true);field.set(asset,config);
        var view=asset.getConfiguration();assertEquals("owned.asset",view.getPid());
        var properties=view.getConfigurationProperties();
        for(String name:runtime)assertFalse(properties.containsKey(name),name);
        assertEquals("owned.cm",properties.get("service.pid"));
        assertEquals("org.eclipse.kura.wire.WireAsset",properties.get("service.factoryPid"));
        assertEquals("owned.driver",properties.get("driver.pid"));assertEquals(10,properties.get("request.timeout"));
        assertEquals(99,properties.get("temperature#component.id"));assertEquals(true,properties.get("temperature#+enabled"));
        properties.put("request.timeout",12);assertEquals(10,supplied.get("request.timeout"));
        for(String name:runtime)assertTrue(supplied.containsKey(name),"internal DS state is retained");
    }
}
