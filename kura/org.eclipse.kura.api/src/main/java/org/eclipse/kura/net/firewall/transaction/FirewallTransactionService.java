/* Copyright (c) 2026 YOFC. SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.net.firewall.transaction;

import java.util.Map;

/**
 * Optional firewall owner API. Values are detached JDK maps, lists, integral
 * numbers, strings, booleans and null, with no provider library dependency.
 * The invoking authenticated UI owns a random 256-bit ownerKey. Keep ownerKey
 * and confirmationToken out of logs, snapshots, URLs and audit payloads.
 * A prepare applies temporarily; a separate explicit confirmation is required.
 * A timeout is UNKNOWN and never permits replay. Retain the original change
 * and query its outcome; absence of evidence remains UNKNOWN.
 */
public interface FirewallTransactionService {
    /** schemaVersion=1; confirmed V3 candidate or null, revision/digest, write grant and transaction. */
    Map<String, Object> getFirewallView() throws FirewallTransactionException;
    /** Typed rule lists and metadata from the same confirmed revision; null lists when unprojectable. */
    FirewallSnapshot getFirewallSnapshot() throws FirewallTransactionException;

    /** change: ownerKey, expectedRevision, sourceDigest, confirmSeconds and complete V3 candidate. */
    Map<String, Object> prepareFirewallChange(String requestId, Map<String, Object> change)
            throws FirewallTransactionException;

    /** Read-only, including during recovery; originalChange is exactly the original prepare input. */
    Map<String, Object> getFirewallOutcome(String originalRequestId, Map<String, Object> originalChange)
            throws FirewallTransactionException;

    Map<String, Object> confirmFirewallChange(String id, String ownerKey, String confirmationToken)
            throws FirewallTransactionException;

    Map<String, Object> rollbackFirewallChange(String id, String ownerKey, String confirmationToken)
            throws FirewallTransactionException;
}
