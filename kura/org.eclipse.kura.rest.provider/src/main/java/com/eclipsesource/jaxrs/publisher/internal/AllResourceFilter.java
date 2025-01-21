/*******************************************************************************
 * Copyright (c) 2021, 2025 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 ******************************************************************************/
package com.eclipsesource.jaxrs.publisher.internal;

import static com.eclipsesource.jaxrs.publisher.ServiceProperties.PUBLISH;

import org.osgi.framework.BundleContext;
import org.osgi.framework.Filter;
import org.osgi.framework.InvalidSyntaxException;

import com.eclipsesource.jaxrs.publisher.ResourceFilter;

public class AllResourceFilter implements ResourceFilter {

    static final String ANY_SERVICE_FILTER = "(&(objectClass=*)(!(" + PUBLISH + "=false)))";

    private final BundleContext context;

    public AllResourceFilter(BundleContext context) {
        validateContext(context);
        this.context = context;
    }

    private void validateContext(BundleContext context) {
        if (context == null) {
            throw new IllegalArgumentException("context must not be null");
        }
    }

    @Override
    public Filter getFilter() {
        try {
            return this.context.createFilter(ANY_SERVICE_FILTER);
        } catch (InvalidSyntaxException willNotHappen) {
            throw new IllegalStateException(willNotHappen);
        }
    }
}
