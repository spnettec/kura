package org.eclipse.kura.asset.provider;

import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.Path;
import java.util.*;
import javax.xml.parsers.DocumentBuilderFactory;
import org.junit.jupiter.api.Test;
import org.w3c.dom.Element;

class BaseAssetFactoryMetadataTest {
    @Test void baseAssetFactoryHasItsOwnDeclarationAndNativeDefinitionFields() throws Exception {
        var factory=DocumentBuilderFactory.newInstance();factory.setNamespaceAware(true);
        var ds=factory.newDocumentBuilder().parse(Path.of("OSGI-INF/AssetComponent.xml").toFile());
        var metadata=factory.newDocumentBuilder().parse(Path.of("OSGI-INF/metatype/org.eclipse.kura.asset.xml").toFile());
        String pid=ds.getDocumentElement().getAttribute("name");assertEquals(BaseAsset.CONF_PID,pid);
        var designation=(Element)metadata.getElementsByTagName("Designate").item(0);
        var ocd=(Element)metadata.getElementsByTagName("OCD").item(0);
        var object=(Element)designation.getElementsByTagName("Object").item(0);
        assertEquals(pid,designation.getAttribute("factoryPid"));assertEquals(pid,designation.getAttribute("pid"));
        assertEquals(pid,ocd.getAttribute("id"));assertEquals(pid,object.getAttribute("ocdref"));
        Map<String,Element> declared=new HashMap<>();var ads=metadata.getElementsByTagName("AD");
        for(int i=0;i<ads.getLength();i++){var ad=(Element)ads.item(i);assertNull(declared.put(ad.getAttribute("id"),ad));}
        var nativeDefinition=new BaseAssetOCD();
        assertEquals(nativeDefinition.getAD().size(),declared.size());
        for(var ad:nativeDefinition.getAD()) {
            var actual=declared.get(ad.getId());assertNotNull(actual);
            assertEquals(ad.getType().name(),actual.getAttribute("type").toUpperCase(Locale.ROOT));
            assertEquals(ad.getCardinality(),Integer.parseInt(actual.getAttribute("cardinality")));
            assertEquals(ad.isRequired(),Boolean.parseBoolean(actual.getAttribute("required")));
            if(ad.getDefault()!=null)assertEquals(ad.getDefault(),actual.getAttribute("default"));
        }
    }
}
