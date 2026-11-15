/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.eclipse.kura.configuration.ConfigurationRevisionService.Reason;
import org.eclipse.kura.configuration.ConfigurationRevisionService.Rejected;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.crypto.CryptoService;
import org.eclipse.kura.core.configuration.metatype.Tocd;
import org.junit.jupiter.api.Test;
import org.osgi.framework.BundleContext;
import org.osgi.framework.ServiceReference;
import org.osgi.service.component.ComponentContext;
import org.osgi.service.metatype.*;

class ProviderDefinitionTest {
    @Test void nativeOneElementCapacityRemainsAContainerInBothBaseAndLocalizedMetadata() throws Exception {
        var definition = new ProviderDefinition(new ProviderDefinition.Source(provider(
                attribute("array", AttributeDefinition.INTEGER, 1, "7"),
                attribute("list", AttributeDefinition.STRING, -1, "x"))), "fixture");
        for (var metadata : List.of(definition, definition.localized("zh"))) {
            assertTrue(metadata.getAD().stream().noneMatch(ad -> ad.isScalarCardinality()));
        }
        var values = definition.defaultProperties(null);
        definition.withValidatedProperties(values, () -> { });
        assertThrows(Rejected.class, () -> definition.withValidatedProperties(Map.of("array", 7), () -> fail("scalar write")));
        assertThrows(Rejected.class, () -> definition.withValidatedProperties(Map.of("list", "x"), () -> fail("scalar write")));
    }
    AttributeDefinition attribute(String id,int type,int cardinality,String... defaults) {
        var attribute=mock(AttributeDefinition.class);when(attribute.getID()).thenReturn(id);when(attribute.getName()).thenReturn(id);
        when(attribute.getType()).thenReturn(type);when(attribute.getCardinality()).thenReturn(cardinality);
        when(attribute.getDefaultValue()).thenReturn(defaults);when(attribute.validate(anyString())).thenReturn("");return attribute;
    }
    MetaTypeProvider provider(AttributeDefinition... attributes) {
        var definition=mock(ObjectClassDefinition.class);when(definition.getID()).thenReturn("shared.definition");
        when(definition.getName()).thenReturn("Provider");when(definition.getAttributeDefinitions(ObjectClassDefinition.ALL)).thenReturn(attributes);
        when(definition.getAttributeDefinitions(ObjectClassDefinition.REQUIRED)).thenReturn(new AttributeDefinition[0]);
        var provider=mock(MetaTypeProvider.class);when(provider.getObjectClassDefinition(anyString(),nullable(String.class))).thenReturn(definition);return provider;
    }
    @Test void stringValidationAndSourceGenerationsRejectStaleWritesWithoutRevealingProviderMessages() throws Exception {
        var text=attribute("text",AttributeDefinition.STRING,0,"valid");
        when(text.validate("bad")).thenReturn("private-provider-detail:bad");
        var source=new ProviderDefinition.Source(provider(text));var definition=new ProviderDefinition(source,"fixture");
        var revision=new ConfigurationRevision();var configuration=new ComponentConfigurationImpl("fixture",definition,Map.of("text","valid"));
        String before=revision.token(configuration,1,0);var calls=new AtomicInteger();
        var invalid=assertThrows(Rejected.class,()->definition.withValidatedProperties(Map.of("text","bad"),calls::incrementAndGet));
        assertEquals(Reason.INVALID_ARGUMENT,invalid.getReason());assertFalse(invalid.getMessage().contains("private-provider-detail"));assertEquals(0,calls.get());
        definition.withValidatedProperties(Map.of("text","valid"),calls::incrementAndGet);assertEquals(1,calls.get());
        source.invalidate();assertThrows(Rejected.class,()->revision.token(configuration,1,0));
        var replacement=new ProviderDefinition(new ProviderDefinition.Source(source.provider),"fixture");
        assertNotEquals(before,revision.token(new ComponentConfigurationImpl("fixture",replacement,Map.of("text","valid")),1,0));
        assertThrows(Rejected.class,()->definition.withValidatedProperties(Map.of("text","valid"),calls::incrementAndGet));assertEquals(1,calls.get());
    }
    @Test void defaultsHaveStandardContainerShapeAndInvalidDefaultsAreOmitted() {
        var list=attribute("list",AttributeDefinition.STRING,-1," a,b ");
        var array=attribute("array",AttributeDefinition.INTEGER,1,"7");
        var invalid=attribute("invalid",AttributeDefinition.BOOLEAN,0,"invalid-boolean");
        var empty=attribute("empty",AttributeDefinition.STRING,-4,new String[0]);
        var definition=new ProviderDefinition(new ProviderDefinition.Source(provider(list,array,invalid,empty)),"fixture");
        var values=definition.defaultProperties(null);assertEquals(List.of(" a,b "),values.get("list"));
        assertArrayEquals(new Integer[]{7},(Integer[])values.get("array"));assertEquals(List.of(),values.get("empty"));assertFalse(values.containsKey("invalid"));
        ((List<String>)values.get("list")).clear();assertEquals(List.of(" a,b "),definition.defaultProperties(null).get("list"));
    }
    @Test void passwordDefaultsStayOutOfUiMetadataAndAreEncryptedForCm() throws Exception {
        var password=attribute("secret",AttributeDefinition.PASSWORD,-4," secret ","");
        var definition=new ProviderDefinition(new ProviderDefinition.Source(provider(password)),"fixture");
        assertNull(definition.getAD().get(0).getDefault());
        var component=mock(ComponentContext.class);var context=mock(BundleContext.class);var reference=mock(ServiceReference.class);var crypto=mock(CryptoService.class);
        when(component.getBundleContext()).thenReturn(context);when(context.getServiceReference(CryptoService.class)).thenReturn(reference);when(context.getService(reference)).thenReturn(crypto);
        when(crypto.decryptAes(any(char[].class))).thenThrow(new org.eclipse.kura.KuraException(org.eclipse.kura.KuraErrorCode.DECODER_ERROR));
        when(crypto.encryptAes(any(char[].class))).thenAnswer(i->("cipher:"+new String((char[])i.getArgument(0))).toCharArray());
        var values=(Collection<?>)definition.defaultProperties(component).get("secret");
        assertEquals(List.of("cipher: secret ","cipher:"),values.stream().map(Object::toString).toList());verify(context).ungetService(reference);
    }
    @Test void defaultsOutsideDeclaredOptionsAreOmittedEvenWhenProviderValidatorAcceptsThem() {
        var valid=attribute("valid",AttributeDefinition.STRING,0,"allowed");
        var invalid=attribute("invalid",AttributeDefinition.STRING,-4,"allowed","outside");
        for (var attribute:List.of(valid,invalid)) {
            when(attribute.getOptionValues()).thenReturn(new String[]{"allowed"});
            when(attribute.getOptionLabels()).thenReturn(new String[]{"Allowed"});
        }
        var definition=new ProviderDefinition(new ProviderDefinition.Source(provider(valid,invalid)),"fixture");
        assertEquals(Map.of("valid","allowed"),definition.defaultProperties(null));
    }
    @Test void unregisterWaitsForAnAlreadyAdmittedWriteThenClosesTheOldDefinition() throws Exception {
        var source=new ProviderDefinition.Source(provider(attribute("text",AttributeDefinition.STRING,0,"ok")));
        var definition=new ProviderDefinition(source,"fixture");var entered=new CountDownLatch(1);var release=new CountDownLatch(1);var removing=new CountDownLatch(1);
        try(var pool=Executors.newFixedThreadPool(2)) {
            var write=pool.submit(()->{definition.withValidatedProperties(Map.of("text","ok"),()->{entered.countDown();try{assertTrue(release.await(2,TimeUnit.SECONDS));}catch(InterruptedException e){throw new AssertionError(e);}});return null;});
            assertTrue(entered.await(2,TimeUnit.SECONDS));var remove=pool.submit(()->{removing.countDown();source.invalidate();});assertTrue(removing.await(2,TimeUnit.SECONDS));
            assertThrows(TimeoutException.class,()->remove.get(100,TimeUnit.MILLISECONDS));release.countDown();write.get(2,TimeUnit.SECONDS);remove.get(2,TimeUnit.SECONDS);
            assertThrows(Rejected.class,()->definition.withValidatedProperties(Map.of("text","ok"),()->fail("old source wrote")));
        } finally { release.countDown(); }
    }

    @Test void coreRejectsProviderValidationBeforeBurningAdmissionOrMarkingOutcomeUncertain() throws Exception {
        var text=attribute("text",AttributeDefinition.STRING,0,"valid");when(text.validate("bad")).thenReturn("rejected");
        var definition=new ProviderDefinition(new ProviderDefinition.Source(provider(text)),"fixture");
        class Fixture extends ConfigurationServiceImpl {
            final Map<String,Object> values=new HashMap<>(Map.of("text","valid"));int writes;
            Fixture() throws Exception {
                var field=ConfigurationServiceImpl.class.getDeclaredField("ocds");field.setAccessible(true);((Map<String,Tocd>)field.get(this)).put("fixture",definition);
            }
            @Override public org.eclipse.kura.configuration.ComponentConfiguration getComponentConfiguration(String pid){return new ComponentConfigurationImpl(pid,definition,this.values);}
            @Override protected boolean revisionTargetTracked(String pid){return true;}
            @Override public synchronized void updateConfiguration(String pid,Map<String,Object> patch,boolean snapshot){this.writes++;this.values.putAll(patch);}
        }
        var fixture=new Fixture();String revision=fixture.readRevision("fixture").revision();
        assertEquals(Reason.INVALID_ARGUMENT,assertThrows(Rejected.class,()->fixture.updateRevision("fixture",revision,Map.of("text","bad"))).getReason());
        assertEquals(0,fixture.writes);assertEquals(revision,fixture.readRevision("fixture").revision());
        fixture.updateRevision("fixture",revision,Map.of("text","valid2"));assertEquals(1,fixture.writes);assertEquals("valid2",fixture.values.get("text"));
    }
    @Test void aWorkerCanReadDefaultsWhileTheCallerHoldsTheWriteSourceLease() throws Exception {
        var source = new ProviderDefinition.Source(provider(attribute("text", AttributeDefinition.STRING, 0, "ok")));
        var definition = new ProviderDefinition(source, "fixture");
        try (var reads = new ProviderConfigurationReads(300, 1, 1)) {
            definition.withSource(() -> assertEquals(Map.of("text", "ok"),
                    reads.read("fixture", () -> definition.defaultProperties(null))));
        }
        source.invalidate();
        assertThrows(IllegalStateException.class, () -> definition.defaultProperties(null));
    }

}
