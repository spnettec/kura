/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration.util;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.nio.file.Path;
import java.nio.file.Files;
import java.util.Collections;
import java.util.List;

import org.eclipse.kura.core.configuration.metatype.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.osgi.framework.*;
import org.osgi.service.metatype.*;

class ComponentMetadataDiscoveryTest {
    @TempDir Path directory;

    Tmetadata metadata(String pid, String id, boolean factory) {
        var result = new Tmetadata(); var definition = new Tocd(); definition.setId(id);
        result.setOCD(definition); var designate = new Tdesignate();
        if (factory) { designate.setFactoryPid(pid); } else { designate.setPid(pid); }
        var object = new Tobject(); object.setOcdref(id); designate.setObject(object);
        result.setDesignate(designate); return result;
    }

    @Test void resourceNamePidAndOcdIdMayDifferForSingletonAndFactory() throws Exception {
        var bundle = mock(Bundle.class); var context = mock(BundleContext.class);
        var reference = mock(ServiceReference.class); var service = mock(MetaTypeService.class);
        var information = mock(MetaTypeInformation.class);
        when(context.getServiceReference(MetaTypeService.class)).thenReturn(reference);
        when(context.getService(reference)).thenReturn(service);
        when(service.getMetaTypeInformation(bundle)).thenReturn(information);
        when(information.getPids()).thenReturn(new String[] {"fixture.single"});
        when(information.getFactoryPids()).thenReturn(new String[] {"fixture.factory"});
        var path = Files.writeString(directory.resolve("arbitrary.xml"), "combined-resource");
        when(bundle.findEntries("OSGI-INF/metatype/", "*.xml", false))
                .thenAnswer(i -> Collections.enumeration(List.of(path.toUri().toURL())));
        var metadata = metadata("fixture.single", "shared.definition", false);
        metadata.setDesignate((Tdesignate) metadata("fixture.factory", "shared.definition", true).getDesignate().get(0));
        try (var utility = mockStatic(ComponentUtil.class, CALLS_REAL_METHODS)) {
            utility.when(() -> ComponentUtil.unmarshal("combined-resource", Tmetadata.class)).thenReturn(metadata);
            var found = ComponentUtil.getMetadata(context, bundle);
            assertEquals(2, found.size());
            assertEquals("shared.definition", ComponentUtil.getOCD(found.get("fixture.single"), "fixture.single").getId());
            assertEquals("shared.definition", ComponentUtil.readObjectClassDefinition(bundle, "fixture.factory").getId());
            verify(context).ungetService(reference);
        }
    }

    @Test void duplicateResourcesAndDanglingReferencesCannotSelectUnrelatedDefaults() throws Exception {
        var bundle = mock(Bundle.class);
        var a = Files.writeString(directory.resolve("a.xml"), "first");
        var b = Files.writeString(directory.resolve("b.xml"), "second");
        when(bundle.findEntries("OSGI-INF/metatype/", "*.xml", false))
                .thenAnswer(i -> Collections.enumeration(List.of(a.toUri().toURL(), b.toUri().toURL())));
        var first = metadata("fixture.single", "first.definition", false);
        var second = metadata("fixture.single", "second.definition", false);
        try (var utility = mockStatic(ComponentUtil.class, CALLS_REAL_METHODS)) {
            utility.when(() -> ComponentUtil.unmarshal("first", Tmetadata.class)).thenReturn(first);
            utility.when(() -> ComponentUtil.unmarshal("second", Tmetadata.class)).thenReturn(second);
            assertNull(ComponentUtil.readMetadata(bundle, "fixture.single"));
        }
        var misleading = new Tocd(); misleading.setId("fixture.single"); first.setOCD(misleading);
        ((Tobject) first.getDesignate().get(0).getObject()).setOcdref("missing.definition");
        assertNull(ComponentUtil.getOCD(first, "fixture.single"));
        assertNull(ComponentUtil.getOCD(null, "fixture.single"));
    }

    @Test void missingMetatypeServiceReturnsNoDefinitions() {
        assertTrue(ComponentUtil.getMetadata(mock(BundleContext.class), mock(Bundle.class)).isEmpty());
    }
}
