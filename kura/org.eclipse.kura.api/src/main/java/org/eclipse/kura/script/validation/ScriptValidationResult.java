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

import java.util.Collections;
import java.util.List;

import org.osgi.annotation.versioning.ProviderType;

/**
 * The outcome of a {@link ScriptValidationService#validate(String, String)} call: either the script compiled cleanly
 * or a list of {@link ScriptValidationError}s describing why it did not.
 *
 * @since 3.1
 */
@ProviderType
public class ScriptValidationResult {

    private final boolean valid;
    private final List<ScriptValidationError> errors;

    private ScriptValidationResult(final boolean valid, final List<ScriptValidationError> errors) {
        this.valid = valid;
        this.errors = errors;
    }

    /**
     * @return a result representing a script that compiled without problems
     */
    public static ScriptValidationResult valid() {
        return new ScriptValidationResult(true, Collections.emptyList());
    }

    /**
     * @param errors
     *            the problems found while compiling the script (must be non empty)
     * @return a result representing a script that failed to compile
     */
    public static ScriptValidationResult invalid(final List<ScriptValidationError> errors) {
        return new ScriptValidationResult(false, Collections.unmodifiableList(errors));
    }

    /**
     * @return {@code true} if the script compiled without errors
     */
    public boolean isValid() {
        return this.valid;
    }

    /**
     * @return the (possibly empty) list of problems found while compiling the script
     */
    public List<ScriptValidationError> getErrors() {
        return this.errors;
    }
}
