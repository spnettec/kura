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
     *            the class to find the bundle context from
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
