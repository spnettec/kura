/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.apache.camel.core.osgi;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;

import org.apache.camel.CamelContext;
import org.apache.camel.Exchange;
import org.apache.camel.LoggingLevel;
import org.apache.camel.NoTypeConversionAvailableException;
import org.apache.camel.RuntimeCamelException;
import org.apache.camel.TypeConverter;
import org.apache.camel.TypeConverterExists;
import org.apache.camel.impl.DefaultCamelContext;
import org.apache.camel.impl.converter.DefaultTypeConverter;
import org.apache.camel.impl.engine.DefaultPackageScanClassResolver;
import org.apache.camel.spi.BulkTypeConverters;
import org.apache.camel.spi.Injector;
import org.apache.camel.spi.PackageScanClassResolver;
import org.apache.camel.spi.TypeConverterLoader;
import org.apache.camel.spi.TypeConverterRegistry;
import org.apache.camel.support.SimpleTypeConverter;
import org.apache.camel.support.service.ServiceHelper;
import org.apache.camel.support.service.ServiceSupport;
import org.osgi.framework.BundleContext;
import org.osgi.framework.ServiceReference;
import org.osgi.util.tracker.ServiceTracker;
import org.osgi.util.tracker.ServiceTrackerCustomizer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class OsgiTypeConverter extends ServiceSupport
        implements TypeConverter, TypeConverterRegistry, ServiceTrackerCustomizer<TypeConverterLoader, Object> {

    private static final Logger LOG = LoggerFactory.getLogger(OsgiTypeConverter.class);

    private final BundleContext bundleContext;
    private CamelContext camelContext;
    private final Injector injector;
    private final ServiceTracker<TypeConverterLoader, Object> tracker;
    private volatile DefaultTypeConverter delegate;

    public OsgiTypeConverter(BundleContext bundleContext, CamelContext camelContext, Injector injector) {
        this.bundleContext = bundleContext;
        this.camelContext = camelContext;
        this.injector = injector;
        this.tracker = new ServiceTracker<>(bundleContext, TypeConverterLoader.class.getName(), this);
    }

    @Override
    public Object addingService(ServiceReference<TypeConverterLoader> serviceReference) {
        LOG.trace("AddingService: {}, Bundle: {}", serviceReference, serviceReference.getBundle());
        TypeConverterLoader loader = bundleContext.getService(serviceReference);
        if (loader != null) {
            try {
                LOG.debug("loading type converter from bundle: {}", serviceReference.getBundle().getSymbolicName());
                if (delegate != null) {
                    ServiceHelper.startService(this.delegate);
                    loader.load(delegate);
                }
            } catch (Throwable t) {
                throw new RuntimeCamelException(
                        "Error loading type converters from service: " + serviceReference + " due: " + t.getMessage(),
                        t);
            }
        }

        return loader;
    }

    @Override
    public void modifiedService(ServiceReference<TypeConverterLoader> serviceReference, Object o) {
    }

    @Override
    public void removedService(ServiceReference<TypeConverterLoader> serviceReference, Object o) {
        LOG.trace("RemovedService: {}, Bundle: {}", serviceReference, serviceReference.getBundle());
        try {
            ServiceHelper.stopService(this.delegate);
        } catch (Exception e) {
            // ignore
            LOG.debug("Error stopping service due: " + e.getMessage() + ". This exception will be ignored.", e);
        }
        // It can force camel to reload the type converter again
        this.delegate = null;
    }

    @Override
    protected void doStart() throws Exception {
        this.tracker.open();
    }

    @Override
    protected void doStop() throws Exception {
        this.tracker.close();
        ServiceHelper.stopService(this.delegate);
        this.delegate = null;
    }

    @Override
    public CamelContext getCamelContext() {
        return camelContext;
    }

    @Override
    public void setCamelContext(CamelContext camelContext) {
        this.camelContext = camelContext;
    }

    @Override
    public boolean allowNull() {
        return getDelegate().allowNull();
    }

    @Override
    public <T> T convertTo(Class<T> type, Object value) {
        return getDelegate().convertTo(type, value);
    }

    @Override
    public <T> T convertTo(Class<T> type, Exchange exchange, Object value) {
        return getDelegate().convertTo(type, exchange, value);
    }

    @Override
    public <T> T mandatoryConvertTo(Class<T> type, Object value) throws NoTypeConversionAvailableException {
        return getDelegate().mandatoryConvertTo(type, value);
    }

    @Override
    public <T> T mandatoryConvertTo(Class<T> type, Exchange exchange, Object value)
            throws NoTypeConversionAvailableException {
        return getDelegate().mandatoryConvertTo(type, exchange, value);
    }

    @Override
    public <T> T tryConvertTo(Class<T> type, Exchange exchange, Object value) {
        return getDelegate().tryConvertTo(type, exchange, value);
    }

    @Override
    public <T> T tryConvertTo(Class<T> type, Object value) {
        return getDelegate().tryConvertTo(type, value);
    }

    @Override
    public void addTypeConverter(Class<?> toType, Class<?> fromType, TypeConverter typeConverter) {
        getDelegate().addTypeConverter(toType, fromType, typeConverter);
    }

    @Override
    public void addTypeConverters(Object typeConverters) {
        getDelegate().addTypeConverters(typeConverters);
    }

    @Override
    public void addBulkTypeConverters(BulkTypeConverters bulkTypeConverters) {
        getDelegate().addBulkTypeConverters(bulkTypeConverters);
    }

    @Override
    public boolean removeTypeConverter(Class<?> toType, Class<?> fromType) {
        return getDelegate().removeTypeConverter(toType, fromType);
    }

    @Override
    public void addFallbackTypeConverter(TypeConverter typeConverter, boolean canPromote) {
        getDelegate().addFallbackTypeConverter(typeConverter, canPromote);
    }

    @Override
    public TypeConverter lookup(Class<?> toType, Class<?> fromType) {
        return getDelegate().lookup(toType, fromType);
    }

    @Override
    public void setInjector(Injector injector) {
        getDelegate().setInjector(injector);
    }

    @Override
    public Injector getInjector() {
        return getDelegate().getInjector();
    }

    @Override
    public Statistics getStatistics() {
        return getDelegate().getStatistics();
    }

    @Override
    public int size() {
        return getDelegate().size();
    }

    @Override
    public LoggingLevel getTypeConverterExistsLoggingLevel() {
        return getDelegate().getTypeConverterExistsLoggingLevel();
    }

    @Override
    public void setTypeConverterExistsLoggingLevel(LoggingLevel loggingLevel) {
        getDelegate().setTypeConverterExistsLoggingLevel(loggingLevel);
    }

    @Override
    public TypeConverterExists getTypeConverterExists() {
        return getDelegate().getTypeConverterExists();
    }

    @Override
    public void setTypeConverterExists(TypeConverterExists typeConverterExists) {
        getDelegate().setTypeConverterExists(typeConverterExists);
    }

    public DefaultTypeConverter getDelegate() {
        if (delegate == null) {
            delegate = createRegistry();
        }
        return delegate;
    }

    protected DefaultTypeConverter createRegistry() {
        // base the osgi type converter on the default type converter
        DefaultTypeConverter answer = new OsgiDefaultTypeConverter(new DefaultPackageScanClassResolver() {

            @Override
            public Set<ClassLoader> getClassLoaders() {
                // we only need classloaders for loading core TypeConverterLoaders
                return new HashSet<>(Arrays.asList(DefaultTypeConverter.class.getClassLoader(),
                        DefaultCamelContext.class.getClassLoader()));
            }
        }, injector, false);

        // inject CamelContext
        answer.setCamelContext(camelContext);

        try {
            // init before loading core converters
            answer.init();
            // only load the core type converters, as OSGi activator will keep track on bundles
            // being installed/uninstalled and load type converters as part of that process
            answer.loadCoreAndFastTypeConverters();
        } catch (Exception e) {
            throw new RuntimeCamelException("Error loading CoreTypeConverter due: " + e.getMessage(), e);
        }

        // Load the type converters the tracker has been tracking
        // Here we need to use the ServiceReference to check the ranking
        ServiceReference<TypeConverterLoader>[] serviceReferences = this.tracker.getServiceReferences();
        if (serviceReferences != null) {
            ArrayList<ServiceReference<TypeConverterLoader>> servicesList = new ArrayList<>(
                    Arrays.asList(serviceReferences));
            // Just make sure we install the high ranking fallback converter at last
            Collections.sort(servicesList);
            for (ServiceReference<TypeConverterLoader> sr : servicesList) {
                try {
                    LOG.debug("loading type converter from bundle: {}", sr.getBundle().getSymbolicName());
                    ((TypeConverterLoader) this.tracker.getService(sr)).load(answer);
                } catch (Throwable t) {
                    throw new RuntimeCamelException(
                            "Error loading type converters from service: " + sr + " due: " + t.getMessage(), t);
                }
            }
        }

        LOG.trace("Created TypeConverter: {}", answer);
        return answer;
    }

    private class OsgiDefaultTypeConverter extends DefaultTypeConverter {

        public OsgiDefaultTypeConverter(PackageScanClassResolver resolver, Injector injector,
                boolean loadTypeConverters) {
            super(resolver, injector, loadTypeConverters);
        }

        @Override
        public void addTypeConverter(Class<?> toType, Class<?> fromType, TypeConverter typeConverter) {
            // favour keeping the converter that was loaded via TypeConverterLoader META-INF file
            // as OSGi loads these first and then gets triggered again later when there is both a META-INF/TypeConverter
            // and META-INF/TypeConverterLoaded file
            // for the same set of type converters and we get duplicates (so this is a way of filtering out duplicates)
            TypeConverter converter = typeMappings.get(toType, fromType);
            if (converter != null && converter != typeConverter) {
                // the converter is already there which we want to keep (optimized via SimpleTypeConverter)
                if (converter instanceof SimpleTypeConverter) {
                    // okay keep this one
                    return;
                }
            }
            super.addTypeConverter(toType, fromType, typeConverter);
        }
    }

}
