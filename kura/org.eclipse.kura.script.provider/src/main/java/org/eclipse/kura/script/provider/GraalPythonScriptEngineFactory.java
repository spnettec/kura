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

public final class GraalPythonScriptEngineFactory extends AbstractGraalScriptEngineFactory {

    @Override
    protected String getLanguageId() {
        return "python";
    }

    @Override
    public String getEngineName() {
        return "GraalVM Python";
    }

    @Override
    public String getLanguageName() {
        return "python";
    }

    @Override
    public List<String> getNames() {
        return List.of("python", "python3", "Python", "graalpython", "graal.python");
    }

    @Override
    public List<String> getExtensions() {
        return List.of("py");
    }

    @Override
    public List<String> getMimeTypes() {
        return List.of("application/x-python", "text/x-python");
    }
}
