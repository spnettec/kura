package org.eclipse.kura.asset.provider;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.nio.file.Path;
import java.util.*;
import org.eclipse.kura.core.configuration.ComponentConfigurationImpl;
import org.junit.jupiter.api.Test;
import org.mockito.MockedStatic;
import org.osgi.framework.*;

class BaseAssetLocalizationTest {
    private static java.net.URL bundleResource(String language) throws Exception {
        var file=Path.of("OSGI-INF/l10n/WireAsset_"+language+".properties").toUri().toURL();
        // ComponentUtil matches the bundle-root path; preserve that URL shape
        // while reading the actual resource bytes rather than a copied fixture.
        return new java.net.URL(null,"owned:/OSGI-INF/l10n/WireAsset_"+language+".properties",
                new java.net.URLStreamHandler() {
                    @Override protected java.net.URLConnection openConnection(java.net.URL url) throws java.io.IOException {
                        return file.openConnection();
                    }
                });
    }
    @Test void nativeAssetFieldsResolveBothSupportedResourceLanguages() throws Exception {
        try(MockedStatic<FrameworkUtil> framework=mockStatic(FrameworkUtil.class)) {
            var bundle=mock(Bundle.class);
            framework.when(()->FrameworkUtil.getBundle(BaseAssetOCD.class)).thenReturn(bundle);
            var en=bundleResource("en");
            var zh=bundleResource("zh");
            when(bundle.findEntries("OSGI-INF/l10n","*.properties",false))
                    .thenAnswer(i->Collections.enumeration(List.of(en,zh)));
            var configuration=new ComponentConfigurationImpl("owned.asset",new BaseAssetOCD(),Map.of());
            for(String language:List.of("en","zh")) {
                var expected=new Properties();try(var in=(language.equals("en")?en:zh).openStream()){expected.load(in);}
                var localized=configuration.getLocalizedDefinition(language);
                for(var ad:localized.getAD()) {
                    String key=switch(ad.getId()){case "request.timeout"->"requestTimeout";case "driver.pid"->"driverpidname";case "asset.desc"->"assetdescname";default->throw new AssertionError(ad.getId());};
                    assertEquals(expected.getProperty(key),ad.getName(),language+":"+ad.getId());
                    assertFalse(ad.getDescription().startsWith("%"));
                }
            }
        }
    }
}
