/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.junit.jupiter.api.Test;

class ProviderConfigurationReadsTest {
    @Test void nestedReadOnlyProvidersDoNotNeedAnotherWorkerAndCyclesAreRejected() throws Exception {
        try (var reads=new ProviderConfigurationReads(1000,1,1)) {
            assertEquals("value",reads.read("outer",()->reads.read("inner",()->"value")));
            assertThrows(ProviderConfigurationReads.Unavailable.class,
                    ()->reads.read("cycle",()->reads.read("cycle",()->"unreachable")));
            assertEquals("next",reads.read("cycle",()->"next"));
        }
    }

    @Test void anOuterTraversalBudgetCannotBeResetByTheNextProvider() throws Exception {
        try (var reads=new ProviderConfigurationReads(500,1,1)) {
            AtomicInteger calls=new AtomicInteger();
            try (var budget=reads.budget()) {
                assertEquals(1,reads.read("first",calls::incrementAndGet));
                Thread.sleep(600);
                assertThrows(ProviderConfigurationReads.Unavailable.class,
                        ()->reads.read("second",calls::incrementAndGet));
                assertEquals(1,calls.get());
            }
            assertEquals(2,reads.read("second",calls::incrementAndGet));
        }
    }

    @Test void uncooperativeCallsCannotCreateMoreWorkersAndQueuedTimeoutsDoNotRunLater() throws Exception {
        var reads=new ProviderConfigurationReads(500,2,2);
        ExecutorService callers=Executors.newFixedThreadPool(4);
        CountDownLatch entered=new CountDownLatch(2),release=new CountDownLatch(1),finished=new CountDownLatch(2);
        Set<String> active=ConcurrentHashMap.newKeySet();AtomicInteger invocations=new AtomicInteger();
        List<Future<?>> requests=new ArrayList<>();
        try {
            for(int i=0;i<4;i++) {
                String key="provider-"+i;
                requests.add(callers.submit(()->reads.read(key,()->{
                    active.add(key);invocations.incrementAndGet();entered.countDown();
                    try { for(;;) { try {release.await();break;}catch(InterruptedException ignored){} } }
                    finally {finished.countDown();}
                    return "late";
                })));
            }
            assertTrue(entered.await(1,TimeUnit.SECONDS));
            for(Future<?> request:requests) {
                ExecutionException failure=assertThrows(ExecutionException.class,()->request.get(2,TimeUnit.SECONDS));
                assertInstanceOf(ProviderConfigurationReads.Unavailable.class,failure.getCause());
            }
            assertEquals(2,invocations.get());
            String stillRunning=active.iterator().next();
            assertThrows(ProviderConfigurationReads.Unavailable.class,
                    ()->reads.read(stillRunning,()->{fail("A timed-out provider is still leased");return "wrong";}));
            reads.close();
            assertThrows(ProviderConfigurationReads.Unavailable.class,()->reads.read("new",()->"wrong"));
        } finally {
            reads.close();release.countDown();callers.shutdownNow();callers.awaitTermination(2,TimeUnit.SECONDS);
        }
        assertTrue(finished.await(1,TimeUnit.SECONDS));
        assertEquals(2,invocations.get());
    }

    @Test void actualProviderFailuresKeepTheirTypedCause() throws Exception {
        try (var reads=new ProviderConfigurationReads(1000,1,1)) {
            KuraException original=new KuraException(KuraErrorCode.CONFIGURATION_ERROR);
            assertSame(original,assertThrows(KuraException.class,()->reads.read("provider",()->{throw original;})));
        }
    }
}
