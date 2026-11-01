/*******************************************************************************
 * Copyright (c) 2026 YOFC and/or its affiliates and others
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.net.transaction;

import java.util.Map;

/**
 * Optional service for the system network owner's explicit transactions.
 * Authentication and user authorization belong to the invoking UI/REST layer;
 * this service does not grant the Kura process system-administration privileges.
 *
 * Values use the version 1 network contract: maps with string keys, lists,
 * strings, booleans, integral numbers and null. Implementations must return
 * detached values, reject unsupported input, and preserve integer precision.
 * This JDK-only boundary does not expose a provider's JSON library or classes.
 *
 * A successful prepare is not a commit. Inspect the returned state and use a
 * separate explicit confirmation after reconnecting over the affected path.
 * Timeout/disconnection does not cancel a request or permit a new write retry.
 * The agent's durable transaction remains authoritative.
 *
 * @since 3.0
 */
public interface NetworkTransactionService {
    /** Confirmed configurations, observed interfaces and the current transaction; schemaVersion=1. */
    Map<String, Object> getNetworkView() throws NetworkTransactionException;

    /**
     * change contains exactly expectedRevision, sourceDigest, confirmSeconds and
     * config. config contains interface, dhcp4, addresses, routes, nameservers,
     * searchDomains, mtu, optional and dhcpMetric. Route entries contain to,
     * via and metric. Unsupported fields/combinations are rejected by the owner.
     * requestId is at most 64 characters and is reused only for identical input.
     */
    Map<String, Object> prepareNetworkChange(String requestId, Map<String, Object> change)
            throws NetworkTransactionException;

    /** Query an owned transaction; a confirmation token is not required. */
    Map<String, Object> getNetworkTransaction(String transactionId) throws NetworkTransactionException;

    /** Tokens are secret: never place them in a URL, log, snapshot or audit payload. */
    Map<String, Object> confirmNetworkChange(String transactionId, String confirmationToken)
            throws NetworkTransactionException;

    Map<String, Object> rollbackNetworkChange(String transactionId, String confirmationToken)
            throws NetworkTransactionException;
}
