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
package org.apache.camel.core.osgi.utils;

import java.lang.reflect.Method;

import org.osgi.framework.Bundle;
import org.osgi.framework.BundleContext;

/**
 * Helper class
 */
public final class BundleContextUtils {

    private BundleContextUtils() {
    }

    /**
     * Retrieve the BundleContext that the given class has been loaded from.
     *
     * @param clazz
     *                  the class to find the bundle context from
     * @return the bundle context or <code>null</code> if it can't be found
     */
    public static BundleContext getBundleContext(Class<?> clazz) {

        // Ideally we should use FrameworkUtil.getBundle(clazz).getBundleContext()
        // but that does not exist in OSGi 4.1, so until we upgrade, we keep that one

        try {
            ClassLoader cl = clazz.getClassLoader();
            Class<?> clClazz = cl.getClass();
            Method mth = null;
            while (clClazz != null) {
                try {
                    mth = clClazz.getDeclaredMethod("getBundle");
                    break;
                } catch (NoSuchMethodException e) {
                    // Ignore
                }
                clClazz = clClazz.getSuperclass();
            }
            if (mth != null) {
                mth.setAccessible(true);
                return ((Bundle) mth.invoke(cl)).getBundleContext();
            }
        } catch (Throwable t) {
            // Ignore
        }

        return null;
    }

}
