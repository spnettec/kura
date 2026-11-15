/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.nio.file.Path;
import java.util.*;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.configuration.SelfConfiguringComponent;
import org.eclipse.kura.core.configuration.metatype.Tocd;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.osgi.framework.ServiceReference;

class ProviderPasswordRepresentationTest {
    @TempDir Path directory;
    @SuppressWarnings("unchecked")
    ComponentConfigurationImpl install(RollbackConvergenceTest.Fixture core,Boolean logical)throws Exception {
        String pid=RollbackPreflightTest.FIRST;
        var ref=(ServiceReference<SelfConfiguringComponent>)core.bundles.getServiceReferences((String)null,"(kura.service.pid="+pid+")")[0];
        var definition=(Tocd)core.bundles.getService(ref).getConfiguration().getDefinition();
        var view=new ComponentConfigurationImpl(pid,definition,Map.of("secret",new Password("encrypted:logical")));
        if(logical!=null)view.setLogicalPasswords(logical);
        when(core.bundles.getService(ref)).thenReturn(()->view);return view;
    }
    @Test void explicitlyStoredSccPasswordIsDecodedWithoutMutatingItsProviderMap()throws Exception {
        try(var core=new RollbackConvergenceTest.Fixture(directory)) {
            core.setCryptoService(RollbackConvergenceTest.crypto());var view=install(core,false);
            var read=core.readRevision(RollbackPreflightTest.FIRST);assertEquals("logical",read.configuration().getConfigurationProperties().get("secret").toString());
            assertEquals("encrypted:logical",view.getConfigurationProperties().get("secret").toString());assertTrue(((ComponentConfigurationImpl)read.configuration()).hasLogicalPasswords());
        }
    }
    @Test void unmarkedLegacySccRetainsItsHistoricalStorageDecodingBoundary()throws Exception {
        try(var core=new RollbackConvergenceTest.Fixture(directory)) {
            core.setCryptoService(RollbackConvergenceTest.crypto());var view=install(core,null);
            assertEquals("logical",core.getComponentConfiguration(RollbackPreflightTest.FIRST).getConfigurationProperties().get("secret").toString());assertEquals("encrypted:logical",view.getConfigurationProperties().get("secret").toString());
        }
    }
    @Test void explicitlyLogicalSccKeepsPasswordContentThatLooksLikeCiphertext()throws Exception {
        try(var core=new RollbackConvergenceTest.Fixture(directory)) {
            var crypto=RollbackConvergenceTest.crypto();core.setCryptoService(crypto);install(core,true);
            assertEquals("encrypted:logical",core.readRevision(RollbackPreflightTest.FIRST).configuration().getConfigurationProperties().get("secret").toString());verify(crypto,never()).decryptAes(any(char[].class));
        }
    }
    @Test void storedSccFlagOverridesSccDefaultWhenSavingAVersionedSnapshot()throws Exception {
        var test=new SnapshotPasswordSourcesTest();test.directory=directory;var core=test.new Fixture();core.scc("stored");
        var value=new ComponentConfigurationImpl("stored",null,Map.of("secret",new Password("encrypted:logical")));value.setLogicalPasswords(false);core.save(List.of(value),List.of());assertEquals("logical",core.secret("stored","secret").toString());
    }
    @Test void logicalExportNormalizesOnlyExplicitStorageValuesAndBindsTheExactDetachedView()throws Exception {
        for(boolean logical:new boolean[]{false,true}) {
            try(var core=new RollbackConvergenceTest.Fixture(directory.resolve(Boolean.toString(logical)))) {
                var crypto=RollbackConvergenceTest.crypto();core.setCryptoService(crypto);var provider=install(core,logical);
                var read=core.readLogicalRevisionView(RollbackPreflightTest.FIRST);
                assertEquals(logical?"encrypted:logical":"logical",read.configuration().getConfigurationProperties().get("secret").toString());
                assertEquals(read.revision(),core.readRevision(RollbackPreflightTest.FIRST).revision());
                read.configuration().getConfigurationProperties().put("secret",new Password("caller changed"));
                assertEquals("encrypted:logical",provider.getConfigurationProperties().get("secret").toString());
                if(logical)verify(crypto,never()).decryptAes(any(char[].class));
            }
        }
    }
}
