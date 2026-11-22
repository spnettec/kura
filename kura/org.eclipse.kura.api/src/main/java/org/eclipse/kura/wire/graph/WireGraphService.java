/*******************************************************************************
 * Copyright (c) 2017, 2020 Eurotech and/or its affiliates and others
 * 
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 * 
 * SPDX-License-Identifier: EPL-2.0
 * 
 * Contributors:
 *  Eurotech
 *******************************************************************************/
package org.eclipse.kura.wire.graph;

import org.eclipse.kura.KuraException;
import org.osgi.annotation.versioning.ProviderType;

/**
 * This interface provides all the needed methods to interact with the
 * WireGraph.
 *
 * @noimplement This interface is not intended to be implemented by clients.
 * @since 1.4
 */
@ProviderType
public interface WireGraphService {

    /** Paired persisted topology and component views for a local graph editor. */
    final class EditingView {
        private final WireGraphConfiguration graph;
        private final java.util.Map<String, org.eclipse.kura.configuration.ConfigurationRevisionService.ReadView> views;

        public EditingView(WireGraphConfiguration graph,
                java.util.Map<String, org.eclipse.kura.configuration.ConfigurationRevisionService.ReadView> views) {
            this.graph = graph;
            this.views = java.util.Collections.unmodifiableMap(new java.util.HashMap<>(views));
        }
        public WireGraphConfiguration graph() { return this.graph; }
        public java.util.Map<String, org.eclipse.kura.configuration.ConfigurationRevisionService.ReadView> views() {
            return this.views;
        }
        @Override public String toString() { return "WireGraphService.EditingView[redacted]"; }
    }

    /**
     * Reads persisted topology and paired revisions, including additional local
     * component dependencies. Unsupported providers reject without issuing a
     * writable legacy view. This is not a runtime health acknowledgement.
     * @since 1.5.0
     */
    default EditingView getForEditing(java.util.Set<String> additionalPids) throws KuraException {
        throw new org.eclipse.kura.configuration.ConfigurationRevisionService.Rejected(
                org.eclipse.kura.configuration.ConfigurationRevisionService.Reason.UNSUPPORTED);
    }

    /**
     * Submits the complete local graph and additional property changes after
     * checking all displayed revisions before the first lifecycle mutation.
     * A non-Rejected failure can follow partial execution and must not be replayed.
     * This does not provide rollback atomicity or authorize remote lifecycle edits.
     * @since 1.5.0
     */
    default void updateIfUnchanged(WireGraphConfiguration graph,
            java.util.List<org.eclipse.kura.configuration.ComponentConfiguration> additionalConfigurations,
            java.util.Map<String, String> expectedRevisions) throws KuraException {
        throw new org.eclipse.kura.configuration.ConfigurationRevisionService.Rejected(
                org.eclipse.kura.configuration.ConfigurationRevisionService.Reason.UNSUPPORTED);
    }

    /**
     * This method allows to create and update the graph, by providing a
     * {@link WireGraphConfiguration}.
     *
     * @param graphConfiguration
     *            A {@link WireGraphConfiguration} object that represents an updated
     *            status of the Wire Graph
     * @throws {@link
     *             KuraException} if the update operation fails
     */
    public void update(WireGraphConfiguration graphConfiguration) throws KuraException;

    /**
     * This method allows to delete the current Wire Graph.
     *
     * @throws {@link
     *             KuraException} if the delete operation fails
     */
    public void delete() throws KuraException;

    /**
     * This method returns the current Wire Graph configuration.
     *
     * @return a {@link WireGraphConfiguration} object that represents the current
     *         configuration of the Wire Graph
     * @throws {@link
     *             KuraException} if the get operation fails
     */
    public WireGraphConfiguration get() throws KuraException;

}
