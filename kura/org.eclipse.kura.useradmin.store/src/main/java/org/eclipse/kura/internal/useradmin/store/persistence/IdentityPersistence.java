/*
 * Copyright (c) 2026 YOFC.
 * SPDX-License-Identifier: EPL-2.0
 */
package org.eclipse.kura.internal.useradmin.store.persistence;

import org.eclipse.kura.KuraException;

/** The active role store completes the change and persists it before returning. */
public interface IdentityPersistence {

    void commit(Change change) throws KuraException;

    @FunctionalInterface
    interface Change {

        void apply() throws KuraException;
    }
}
