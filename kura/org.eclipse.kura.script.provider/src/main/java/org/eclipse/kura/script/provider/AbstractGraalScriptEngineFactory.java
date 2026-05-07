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

import javax.script.ScriptEngine;
import javax.script.ScriptEngineFactory;

/**
 * Minimal JSR-223 {@link ScriptEngineFactory} that exposes a GraalVM Polyglot
 * language as a standard {@code javax.script} engine. GraalVM only ships a
 * JSR-223 adapter for JavaScript; everything else (Python, WebAssembly, ...)
 * has to be wrapped by hand.
 */
abstract class AbstractGraalScriptEngineFactory implements ScriptEngineFactory {

    @Override
    public final ScriptEngine getScriptEngine() {
        return new GraalScriptEngine(this, getLanguageId());
    }

    /** Truffle language id, e.g. {@code "python"} or {@code "wasm"}. */
    protected abstract String getLanguageId();

    @Override
    public String getEngineVersion() {
        return "1.0";
    }

    @Override
    public String getLanguageVersion() {
        return "graalvm";
    }

    @Override
    public Object getParameter(String key) {
        switch (key) {
        case ScriptEngine.NAME:
            return getLanguageName();
        case ScriptEngine.ENGINE:
            return getEngineName();
        case ScriptEngine.ENGINE_VERSION:
            return getEngineVersion();
        case ScriptEngine.LANGUAGE:
            return getLanguageName();
        case ScriptEngine.LANGUAGE_VERSION:
            return getLanguageVersion();
        case "THREADING":
            return null;
        default:
            return null;
        }
    }

    @Override
    public String getMethodCallSyntax(String obj, String method, String... args) {
        StringBuilder sb = new StringBuilder().append(obj).append('.').append(method).append('(');
        for (int i = 0; i < args.length; i++) {
            if (i > 0) {
                sb.append(", ");
            }
            sb.append(args[i]);
        }
        return sb.append(')').toString();
    }

    @Override
    public String getOutputStatement(String toDisplay) {
        return "print(" + toDisplay + ")";
    }

    @Override
    public String getProgram(String... statements) {
        StringBuilder sb = new StringBuilder();
        for (String stmt : statements) {
            sb.append(stmt).append('\n');
        }
        return sb.toString();
    }

    @Override
    public List<String> getExtensions() {
        return List.of();
    }

    @Override
    public List<String> getMimeTypes() {
        return List.of();
    }

    @Override
    public List<String> getNames() {
        return List.of();
    }
}
