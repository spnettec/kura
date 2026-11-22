package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.nio.file.Path;
import java.util.*;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.configuration.SelfConfiguringComponent;
import org.eclipse.kura.core.configuration.metatype.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.osgi.framework.ServiceReference;

class SelfConfiguringContainerMetadataTest {
    @TempDir Path directory;
    @SuppressWarnings("unchecked")
    private void provider(RollbackConvergenceTest.Fixture core, Tscalar type, Object value) throws Exception {
        String pid=RollbackPreflightTest.FIRST;
        var definition=new Tocd();definition.setId(pid);
        var ad=new Tad();ad.setId("typed");ad.setType(type);ad.setCardinality(-8);definition.addAD(ad);
        var reference=(ServiceReference<SelfConfiguringComponent>)core.bundles.getServiceReferences((String)null,"(kura.service.pid="+pid+")")[0];
        when(core.bundles.getService(reference)).thenReturn(()->new ComponentConfigurationImpl(pid,definition,new HashMap<>(Map.of("typed",value))));
    }
    @Test void declaredPasswordContainersAreVisibleThroughTheRealSccReadEntry()throws Exception {
        try(var core=new RollbackConvergenceTest.Fixture(directory)) {
            for(Object value:List.of(new Vector<>(List.of(new Password("plain"),new Password(""))),new Vector<>(),new Password[]{new Password("plain"),new Password("")},new Password[0])) {
                provider(core,Tscalar.PASSWORD,value);
                var read=core.getComponentConfiguration(RollbackPreflightTest.FIRST);
                assertNotNull(read);assertTrue(ConfigurationRevision.sameValue(value,read.getConfigurationProperties().get("typed")));
            }
        }
    }
    @Test void mixedOrNestedContainersCannotMasqueradeAsTheDeclaredScalarType()throws Exception {
        try(var core=new RollbackConvergenceTest.Fixture(directory)) {
            for(Object value:List.of(new Vector<>(List.of(new Password("plain"),"wrong")),new Vector<>(List.of(List.of(new Password("plain")))),new Password[]{null})) {
                provider(core,Tscalar.PASSWORD,value);assertNull(core.getComponentConfiguration(RollbackPreflightTest.FIRST));
            }
        }
    }
    @Test void primitiveArrayMetadataReadsDoNotCastToObjectArray()throws Exception {
        try(var core=new RollbackConvergenceTest.Fixture(directory)) {
            provider(core,Tscalar.INTEGER,new int[]{1,2});assertNotNull(core.getComponentConfiguration(RollbackPreflightTest.FIRST));
            provider(core,Tscalar.INTEGER,new int[0]);assertNotNull(core.getComponentConfiguration(RollbackPreflightTest.FIRST));
        }
    }
    @Test void scalarAndArrayTypeMismatchRejectsThePublicConfiguration()throws Exception {
        try(var core=new RollbackConvergenceTest.Fixture(directory)) {
            for(Object value:List.of("wrong",new String[]{"wrong"},new String[0])) {
                provider(core,Tscalar.PASSWORD,value);assertNull(core.getComponentConfiguration(RollbackPreflightTest.FIRST));
            }
        }
    }
}
