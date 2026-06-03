/*******************************************************************************
 * Copyright (c) 2025 Eclipse Kura contributors and others
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * https://www.eclipse.org/legal/epl-2.0
 *
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.script.validation;

import org.osgi.annotation.versioning.ProviderType;

/**
 * Describes a single problem found while validating (compiling) a script.
 *
 * @since 3.1
 */
@ProviderType
public class ScriptValidationError {

    /** Severity reported for a syntax / compilation problem. */
    public static final String SEVERITY_ERROR = "error";

    /** Severity reported for a non fatal problem. */
    public static final String SEVERITY_WARNING = "warning";

    private final int line;
    private final int column;
    private final String message;
    private final String severity;

    /**
     * Creates a new error.
     *
     * @param line
     *            the 1-based line number the problem refers to, or {@code -1} if unknown
     * @param column
     *            the 1-based column number the problem refers to, or {@code -1} if unknown
     * @param message
     *            a human readable description of the problem
     * @param severity
     *            one of {@link #SEVERITY_ERROR} or {@link #SEVERITY_WARNING}
     */
    public ScriptValidationError(final int line, final int column, final String message, final String severity) {
        this.line = line;
        this.column = column;
        this.message = message;
        this.severity = severity;
    }

    /**
     * @return the 1-based line number the problem refers to, or {@code -1} if unknown
     */
    public int getLine() {
        return this.line;
    }

    /**
     * @return the 1-based column number the problem refers to, or {@code -1} if unknown
     */
    public int getColumn() {
        return this.column;
    }

    /**
     * @return a human readable description of the problem
     */
    public String getMessage() {
        return this.message;
    }

    /**
     * @return the severity, one of {@link #SEVERITY_ERROR} or {@link #SEVERITY_WARNING}
     */
    public String getSeverity() {
        return this.severity;
    }

    @Override
    public String toString() {
        return "ScriptValidationError [line=" + this.line + ", column=" + this.column + ", severity=" + this.severity
                + ", message=" + this.message + "]";
    }
}
