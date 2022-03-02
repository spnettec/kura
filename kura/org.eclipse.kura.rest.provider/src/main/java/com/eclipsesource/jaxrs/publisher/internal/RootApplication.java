/*******************************************************************************
 * Copyright (c) 2012,2015 EclipseSource and others.
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *
 * Contributors:
 *    Holger Staudacher - initial API and implementation
 *    Dragos Dascalita  - added properties
 *    Ivan Iliev - Performance Optimizations
 ******************************************************************************/
package com.eclipsesource.jaxrs.publisher.internal;

import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedList;
import java.util.List;
import java.util.Map;
import java.util.Set;

import javax.ws.rs.core.Application;

public class RootApplication extends Application {

    private final Map<String, Object> properties;
    private final List<Object> resources;
    private final Object lock = new Object();
    private volatile boolean dirty;

    public RootApplication() {
        this.resources = new LinkedList<>();
        this.properties = new HashMap<>();
    }

    void addResource(Object resource) {
        synchronized (this.lock) {
            this.resources.add(resource);
            this.dirty = true;
        }
    }

    void removeResource(Object resource) {
        synchronized (this.lock) {
            this.resources.remove(resource);
            this.dirty = true;
        }
    }

    boolean hasResources() {
        return !this.resources.isEmpty();
    }

    @Override
    public Set<Object> getSingletons() {
        synchronized (this.lock) {
            Set<Object> currentResources = getResources();
            // when this method is called jersey has obtained our resources as they are now, we mark the
            // application as not dirty, next time a resource is added it will mark it as dirty again.
            this.dirty = false;
            return currentResources;
        }
    }

    public Set<Object> getResources() {
        Set<Object> singletons = new HashSet<>(super.getSingletons());
        singletons.addAll(this.resources);
        return singletons;
    }

    @Override
    public Map<String, Object> getProperties() {
        return this.properties;
    }

    public void addProperty(String key, Object value) {
        Object oldValue = this.properties.get(key);
        this.properties.put(key, value);
        // if application is not dirty but the current property is changed - mark it
        synchronized (this.lock) {
            if (!this.dirty && value != oldValue && (value == null || !value.equals(oldValue))) {
                this.dirty = true;
            }
        }
    }

    public void addProperties(Map<String, Object> properties) {
        for (Map.Entry<String, Object> entry : properties.entrySet()) {
            addProperty(entry.getKey(), entry.getValue());
        }
    }

    public boolean isDirty() {
        synchronized (this.lock) {
            return this.dirty;
        }
    }

    public void setDirty(boolean isDirty) {
        synchronized (this.lock) {
            this.dirty = isDirty;
        }
    }
}
