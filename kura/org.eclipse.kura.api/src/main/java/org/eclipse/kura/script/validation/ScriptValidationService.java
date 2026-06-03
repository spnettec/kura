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

import java.util.Set;

import org.osgi.annotation.versioning.ProviderType;

/**
 * Compiles a script without executing it in order to surface syntax / compilation errors back to the user.
 * <p>
 * This is meant to back interactive script editors (for example the Wires script filter or the Camel init code) so
 * that an author can validate what was typed before saving it, instead of having to inspect the gateway logs after the
 * fact.
 *
 * @since 3.1
 */
@ProviderType
public interface ScriptValidationService {

    /**
     * Compiles (but does not run) the given script and reports any syntax / compilation problems.
     *
     * @param language
     *            the script language id, for example {@code js}, {@code groovy}, {@code python} or {@code wasm}
     * @param script
     *            the script source to validate
     * @return a {@link ScriptValidationResult} describing whether the script compiled and, if not, the problems found
     */
    ScriptValidationResult validate(String language, String script);

    /**
     * @return the set of language ids this service is able to validate
     */
    Set<String> getSupportedLanguages();
}
