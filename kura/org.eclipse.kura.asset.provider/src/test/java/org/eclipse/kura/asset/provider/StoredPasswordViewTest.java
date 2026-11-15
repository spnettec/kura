/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.asset.provider;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.util.*;
import java.util.stream.Stream;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.eclipse.kura.core.configuration.metatype.*;
import org.eclipse.kura.internal.asset.provider.BaseAssetConfiguration;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

class StoredPasswordViewTest {
    static Stream<Arguments> storedShapes(){return Stream.of(Arguments.of("stored-scalar"),Arguments.of((Object)new String[]{"stored-first",""}),Arguments.of(new Vector<>(List.of("stored-vector",""))));}
    @ParameterizedTest @MethodSource("storedShapes")
    void dynamicDriverPasswordDescriptorProducesAnExplicitStoredTypedView(Object stored)throws Exception {
        var definition=new Tocd();definition.setId("owned.asset");var ad=new Tad();ad.setId("channel#secret");ad.setType(Tscalar.PASSWORD);definition.addAD(ad);
        Map<String,Object> supplied=new HashMap<>(Map.of("kura.service.pid","owned.asset","driver.pid","owned.driver","channel#secret",stored));
        var config=mock(BaseAssetConfiguration.class);when(config.getProperties()).thenReturn(supplied);when(config.getDefinition()).thenReturn(definition);
        var asset=new BaseAsset();var field=BaseAsset.class.getDeclaredField("config");field.setAccessible(true);field.set(asset,config);
        var view=(ComponentConfigurationImpl)asset.getConfiguration();Object value=view.getConfigurationProperties().get("channel#secret");
        assertTrue(view.hasPasswordRepresentation());assertFalse(view.hasLogicalPasswords());
        if(stored instanceof String text){assertInstanceOf(Password.class,value);assertEquals(text,value.toString());}
        else if(stored instanceof String[] strings){assertInstanceOf(Password[].class,value);var passwords=(Password[])value;assertEquals(strings.length,passwords.length);for(int i=0;i<strings.length;i++)assertEquals(strings[i],passwords[i].toString());}
        else {assertInstanceOf(Vector.class,value);var passwords=(Vector<?>)value;assertEquals("stored-vector",passwords.get(0).toString());assertEquals("",passwords.get(1).toString());}
        assertSame(stored,supplied.get("channel#secret"));view.getConfigurationProperties().put("driver.pid","changed view");assertEquals("owned.driver",supplied.get("driver.pid"));
    }
}
