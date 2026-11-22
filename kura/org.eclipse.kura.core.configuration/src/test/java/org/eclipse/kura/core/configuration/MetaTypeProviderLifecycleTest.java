/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.BooleanSupplier;
import org.eclipse.kura.configuration.ConfigurationRevisionService.Rejected;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.osgi.framework.*;
import org.osgi.framework.launch.*;
import org.osgi.service.metatype.*;

class MetaTypeProviderLifecycleTest {
    @TempDir Path directory;
    void await(BooleanSupplier condition) throws Exception {
        for(int i=0;i<500;i++){if(condition.getAsBoolean()){return;}Thread.sleep(10);}fail("metadata event deadline");
    }
    MetaTypeProvider provider(String name) {
        var attribute=mock(AttributeDefinition.class);when(attribute.getID()).thenReturn("text");when(attribute.getName()).thenReturn("Text");when(attribute.getType()).thenReturn(AttributeDefinition.STRING);when(attribute.validate(anyString())).thenReturn("");
        var definition=mock(ObjectClassDefinition.class);when(definition.getID()).thenReturn("shared.definition");when(definition.getName()).thenReturn(name);
        when(definition.getAttributeDefinitions(ObjectClassDefinition.ALL)).thenReturn(new AttributeDefinition[]{attribute});
        when(definition.getAttributeDefinitions(ObjectClassDefinition.REQUIRED)).thenReturn(new AttributeDefinition[0]);
        var provider=mock(MetaTypeProvider.class);when(provider.getObjectClassDefinition(anyString(),nullable(String.class))).thenReturn(definition);return provider;
    }
    Dictionary<String,Object> properties(String singleton,String factory,int ranking) {
        var values=new Hashtable<String,Object>();if(singleton!=null){values.put(MetaTypeProvider.METATYPE_PID,List.of(singleton));}
        if(factory!=null){values.put(MetaTypeProvider.METATYPE_FACTORY_PID,new String[]{factory});}values.put(Constants.SERVICE_RANKING,ranking);return values;
    }
    @Test void realRegistryRegistrationModificationPriorityAndRemovalInvalidateOldSources() throws Exception {
        Framework framework=ServiceLoader.load(FrameworkFactory.class).findFirst().orElseThrow().newFramework(Map.of(Constants.FRAMEWORK_STORAGE,directory.resolve("framework").toString(),Constants.FRAMEWORK_SYSTEMPACKAGES_EXTRA,"org.osgi.service.metatype;version=1.4.1,org.osgi.service.cm;version=1.6.1"));
        framework.init();framework.start();var context=framework.getBundleContext();var service=mock(ConfigurationServiceImpl.class);
        var current=new AtomicReference<Map<String,MetadataDefinition>>(Map.of());
        doAnswer(invocation->{current.set(Map.copyOf(invocation.getArgument(1)));return null;}).when(service).replaceBundleMetadata(any(),anyMap());
        var tracker=new ComponentMetaTypeBundleTracker(context,service);
        try {
            tracker.open();var lower=context.registerService(MetaTypeProvider.class,provider("lower"),properties("fixture.single","fixture.factory",1));
            await(()->current.get().containsKey("fixture.factory"));assertTrue(current.get().get("fixture.factory").factory());assertFalse(current.get().get("fixture.single").factory());
            var old=(ProviderDefinition)current.get().get("fixture.single").definition();
            lower.setProperties(properties("fixture.renamed","fixture.factory",1));
            await(()->current.get().containsKey("fixture.renamed")&&!current.get().containsKey("fixture.single"));assertThrows(Rejected.class,old::generation);
            var higher=context.registerService(MetaTypeProvider.class,provider("higher"),properties("fixture.renamed",null,10));
            await(()->"higher".equals(current.get().get("fixture.renamed").definition().getName()));var selected=(ProviderDefinition)current.get().get("fixture.renamed").definition();
            higher.unregister();await(()->current.get().containsKey("fixture.renamed")&&"lower".equals(current.get().get("fixture.renamed").definition().getName()));assertThrows(Rejected.class,selected::generation);
            lower.unregister();await(()->current.get().isEmpty());
        } finally {tracker.close();framework.stop();assertNotEquals(FrameworkEvent.WAIT_TIMEDOUT,framework.waitForStop(5000).getType());}
    }
}
