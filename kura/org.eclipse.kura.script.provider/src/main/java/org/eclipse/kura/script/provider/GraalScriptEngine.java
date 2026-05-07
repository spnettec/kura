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

import java.io.BufferedReader;
import java.io.IOException;
import java.io.Reader;

import javax.script.AbstractScriptEngine;
import javax.script.Bindings;
import javax.script.Compilable;
import javax.script.CompiledScript;
import javax.script.ScriptContext;
import javax.script.ScriptEngine;
import javax.script.ScriptEngineFactory;
import javax.script.ScriptException;
import javax.script.SimpleBindings;

import org.graalvm.polyglot.Context;
import org.graalvm.polyglot.PolyglotException;
import org.graalvm.polyglot.Source;
import org.graalvm.polyglot.Value;

/**
 * Bridges {@code javax.script} onto a GraalVM {@link Context} for a single
 * language id (e.g. {@code python}, {@code wasm}). One {@link Context} is
 * created lazily per engine instance and reused across {@code eval} calls so
 * that bindings and imports persist, mirroring what GraalJSScriptEngine does.
 */
final class GraalScriptEngine extends AbstractScriptEngine implements Compilable {

    private final ScriptEngineFactory factory;
    private final String languageId;
    private Context context;

    GraalScriptEngine(ScriptEngineFactory factory, String languageId) {
        this.factory = factory;
        this.languageId = languageId;
    }

    @Override
    public ScriptEngineFactory getFactory() {
        return this.factory;
    }

    @Override
    public Bindings createBindings() {
        return new SimpleBindings();
    }

    @Override
    public Object eval(String script, ScriptContext scriptContext) throws ScriptException {
        return evalSource(Source.newBuilder(this.languageId, script, "<script>").buildLiteral(), scriptContext);
    }

    @Override
    public Object eval(Reader reader, ScriptContext scriptContext) throws ScriptException {
        return eval(readAll(reader), scriptContext);
    }

    @Override
    public CompiledScript compile(String script) throws ScriptException {
        Source source = Source.newBuilder(this.languageId, script, "<script>").buildLiteral();
        return new GraalCompiledScript(source);
    }

    @Override
    public CompiledScript compile(Reader reader) throws ScriptException {
        return compile(readAll(reader));
    }

    private Object evalSource(Source source, ScriptContext scriptContext) throws ScriptException {
        Context ctx = ensureContext();
        applyBindings(ctx, scriptContext.getBindings(ScriptContext.ENGINE_SCOPE));
        try {
            Value result = ctx.eval(source);
            return unwrap(result);
        } catch (PolyglotException e) {
            throw new ScriptException(e);
        }
    }

    private synchronized Context ensureContext() {
        if (this.context == null) {
            this.context = Context.newBuilder(this.languageId).allowAllAccess(true).build();
        }
        return this.context;
    }

    private void applyBindings(Context ctx, Bindings bindings) {
        if (bindings == null || bindings.isEmpty()) {
            return;
        }
        Value polyBindings = ctx.getBindings(this.languageId);
        for (var entry : bindings.entrySet()) {
            polyBindings.putMember(entry.getKey(), entry.getValue());
        }
    }

    private static Object unwrap(Value value) {
        if (value == null || value.isNull()) {
            return null;
        }
        if (value.isHostObject()) {
            return value.asHostObject();
        }
        if (value.isString()) {
            return value.asString();
        }
        if (value.isBoolean()) {
            return value.asBoolean();
        }
        if (value.isNumber()) {
            if (value.fitsInLong()) {
                return value.asLong();
            }
            if (value.fitsInDouble()) {
                return value.asDouble();
            }
        }
        return value;
    }

    private static String readAll(Reader reader) throws ScriptException {
        StringBuilder sb = new StringBuilder();
        try (BufferedReader br = new BufferedReader(reader)) {
            char[] buf = new char[4096];
            int n;
            while ((n = br.read(buf)) >= 0) {
                sb.append(buf, 0, n);
            }
        } catch (IOException e) {
            throw new ScriptException(e);
        }
        return sb.toString();
    }

    private final class GraalCompiledScript extends CompiledScript {

        private final Source source;

        GraalCompiledScript(Source source) {
            this.source = source;
        }

        @Override
        public Object eval(ScriptContext scriptContext) throws ScriptException {
            return evalSource(this.source, scriptContext);
        }

        @Override
        public ScriptEngine getEngine() {
            return GraalScriptEngine.this;
        }
    }
}
