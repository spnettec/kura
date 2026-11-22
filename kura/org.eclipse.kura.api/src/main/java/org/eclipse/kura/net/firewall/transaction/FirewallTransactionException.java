/* Copyright (c) 2026 YOFC. SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.net.firewall.transaction;

/** Stable protocol code and correlation ID, without input or secret contents. */
public final class FirewallTransactionException extends Exception {
    private static final long serialVersionUID = 1L;
    private final String code;
    private final String requestId;
    public FirewallTransactionException(String code, String requestId) {
        super(code); this.code = code; this.requestId = requestId;
    }
    public String getCode() { return this.code; }
    public String getRequestId() { return this.requestId; }
}
