/*******************************************************************************
 * Copyright (c) 2025 Eclipse Kura contributors and others
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * https://www.eclipse.org/legal/epl-2.0
 *
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.script.provider;

import java.util.List;

public final class GraalWasmScriptEngineFactory extends AbstractGraalScriptEngineFactory {

    @Override
    protected String getLanguageId() {
        return "wasm";
    }

    @Override
    public String getEngineName() {
        return "GraalVM WebAssembly";
    }

    @Override
    public String getLanguageName() {
        return "wasm";
    }

    @Override
    public List<String> getNames() {
        return List.of("wasm", "WebAssembly", "graal.wasm");
    }

    @Override
    public List<String> getExtensions() {
        return List.of("wasm", "wat");
    }

    @Override
    public List<String> getMimeTypes() {
        return List.of("application/wasm");
    }
}
