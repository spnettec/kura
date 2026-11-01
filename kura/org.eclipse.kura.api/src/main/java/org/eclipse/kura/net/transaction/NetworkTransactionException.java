/*******************************************************************************
 * Copyright (c) 2026 YOFC and/or its affiliates and others
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.net.transaction;

/** A stable network protocol code and correlation ID, without input or token contents. */
public final class NetworkTransactionException extends Exception {
    private static final long serialVersionUID = 1L;
    private final String code;
    private final String requestId;

    public NetworkTransactionException(String code, String requestId) {
        super(code);
        this.code = code;
        this.requestId = requestId;
    }

    public String getCode() { return this.code; }
    public String getRequestId() { return this.requestId; }
}
