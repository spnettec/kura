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

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.function.Supplier;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.codehaus.groovy.control.CompilationFailedException;
import org.codehaus.groovy.control.CompilationUnit;
import org.codehaus.groovy.control.MultipleCompilationErrorsException;
import org.codehaus.groovy.control.Phases;
import org.codehaus.groovy.control.messages.Message;
import org.codehaus.groovy.control.messages.SyntaxErrorMessage;
import org.codehaus.groovy.syntax.SyntaxException;
import org.eclipse.kura.script.validation.ScriptValidationError;
import org.eclipse.kura.script.validation.ScriptValidationResult;
import org.eclipse.kura.script.validation.ScriptValidationService;
import org.graalvm.polyglot.Context;
import org.graalvm.polyglot.PolyglotException;
import org.graalvm.polyglot.Source;
import org.graalvm.polyglot.SourceSection;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * {@link ScriptValidationService} backed by the engines bundled with this provider.
 * <p>
 * {@code groovy} is validated by compiling it to the {@link Phases#CONVERSION} phase with a {@link CompilationUnit}
 * (this provider already {@code Require-Bundle}s groovy). This catches syntax errors but deliberately stops before
 * import/type resolution, so scripts referencing classes only present in their runtime context are not flagged. It
 * also avoids the {@code javax.script} {@code ScriptEngineManager(ClassLoader)} discovery, which does not find the
 * factories under Equinox + Aries SpiFly. GraalVM polyglot languages ({@code js}, {@code python}, {@code wasm}) are
 * validated by
 * {@linkplain Context#parse(Source) parsing} the source without evaluating it. The polyglot path is guarded against
 * runtime/linkage failures (the GraalVM optimizing runtime is not always loadable under Equinox + Aries SpiFly): in
 * that case a warning is returned rather than failing the request.
 */
public class ScriptValidationServiceImpl implements ScriptValidationService {

    private static final Logger logger = LoggerFactory.getLogger(ScriptValidationServiceImpl.class);

    private static final String LANG_JS = "js";
    private static final String LANG_GROOVY = "groovy";
    private static final String LANG_PYTHON = "python";
    private static final String LANG_WASM = "wasm";

    private static final Set<String> POLYGLOT_LANGUAGES = new HashSet<>(
            Arrays.asList(LANG_JS, LANG_PYTHON, LANG_WASM));

    // Matches a "<source>:line:column" position embedded in a polyglot error message (fallback when no SourceSection).
    private static final Pattern MESSAGE_LOCATION_PATTERN = Pattern.compile(":(\\d+):(\\d+)");

    // Advertised to callers (UI dispatches by these). Includes the aliases the editor may send (e.g. ACE's
    // "javascript"); validate() normalizes them via normalizeLanguage().
    private static final Set<String> SUPPORTED_LANGUAGES = Collections.unmodifiableSet(new LinkedHashSet<>(
            Arrays.asList(LANG_JS, "javascript", "ecmascript", LANG_GROOVY, LANG_PYTHON, "py", LANG_WASM)));

    @Override
    public Set<String> getSupportedLanguages() {
        return SUPPORTED_LANGUAGES;
    }

    @Override
    public ScriptValidationResult validate(final String language, final String script) {
        final String normalizedLanguage = normalizeLanguage(language);

        if (script == null || script.trim().isEmpty()) {
            return ScriptValidationResult.valid();
        }

        if (LANG_GROOVY.equals(normalizedLanguage)) {
            return withBundleContextClassLoader(() -> validateGroovy(script));
        }

        if (POLYGLOT_LANGUAGES.contains(normalizedLanguage)) {
            return withBundleContextClassLoader(() -> validateWithPolyglot(normalizedLanguage, script));
        }

        logger.debug("No validator available for language '{}', skipping validation.", language);
        return ScriptValidationResult.valid();
    }

    /**
     * Runs the given task with the thread context class loader temporarily set to this bundle's class loader. The
     * validation call arrives on a web-server request thread whose TCCL cannot see the groovy compiler internals nor
     * the GraalVM languages bundled here; the groovy compiler and the polyglot language discovery both consult the
     * TCCL, so this swap is required for them to work under OSGi.
     */
    private ScriptValidationResult withBundleContextClassLoader(final Supplier<ScriptValidationResult> task) {
        final Thread current = Thread.currentThread();
        final ClassLoader previous = current.getContextClassLoader();
        current.setContextClassLoader(getClass().getClassLoader());
        try {
            return task.get();
        } finally {
            current.setContextClassLoader(previous);
        }
    }

    private static String normalizeLanguage(final String language) {
        if (language == null) {
            return "";
        }

        final String normalized = language.trim().toLowerCase();

        switch (normalized) {
        case "javascript":
        case "ecmascript":
        case "graal.js":
            return LANG_JS;
        case "py":
            return LANG_PYTHON;
        default:
            return normalized;
        }
    }

    private ScriptValidationResult validateGroovy(final String script) {
        try {
            final CompilationUnit unit = new CompilationUnit();
            unit.addSource("Validate.groovy", script);
            // Compile only up to the conversion (parse / AST build) phase: this surfaces syntax errors without
            // resolving imports or types, which would otherwise fail for scripts that legitimately reference classes
            // only available in their runtime context (e.g. Camel / Vert.x types bound at execution time) and produce
            // misleading "unable to resolve class" errors.
            unit.compile(Phases.CONVERSION);
            return ScriptValidationResult.valid();
        } catch (final MultipleCompilationErrorsException e) {
            return ScriptValidationResult.invalid(toErrors(e));
        } catch (final CompilationFailedException e) {
            return ScriptValidationResult.invalid(Collections.singletonList(
                    new ScriptValidationError(-1, -1, e.getMessage(), ScriptValidationError.SEVERITY_ERROR)));
        } catch (final Exception e) {
            logger.warn("Unexpected error while validating groovy script.", e);
            return ScriptValidationResult.invalid(Collections.singletonList(
                    new ScriptValidationError(-1, -1, e.getMessage(), ScriptValidationError.SEVERITY_ERROR)));
        }
    }

    private ScriptValidationResult validateWithPolyglot(final String languageId, final String script) {
        try (Context context = Context.newBuilder(languageId).build()) {
            final Source source = Source.newBuilder(languageId, script, "<validate>").buildLiteral();
            context.parse(source);
            return ScriptValidationResult.valid();
        } catch (final PolyglotException e) {
            return ScriptValidationResult.invalid(Collections.singletonList(toError(e)));
        } catch (final Throwable e) {
            // The GraalVM optimizing runtime is not always loadable under Equinox + Aries SpiFly (ClassFormatError /
            // LinkageError while weaving the Truffle ServiceLoader providers). Degrade gracefully instead of failing
            // the RPC so the rest of the editor keeps working.
            logger.warn("Script validation engine unavailable for language '{}'.", languageId, e);
            return ScriptValidationResult.invalid(Collections.singletonList(new ScriptValidationError(-1, -1,
                    "Script validation engine is unavailable in this runtime (" + e.getClass().getSimpleName() + ": "
                            + e.getMessage() + ")",
                    ScriptValidationError.SEVERITY_WARNING)));
        }
    }

    private static List<ScriptValidationError> toErrors(final MultipleCompilationErrorsException e) {
        final List<ScriptValidationError> errors = new ArrayList<>();

        for (final Object raw : e.getErrorCollector().getErrors()) {
            if (raw instanceof SyntaxErrorMessage) {
                final SyntaxException se = ((SyntaxErrorMessage) raw).getCause();
                errors.add(new ScriptValidationError(se.getStartLine(), se.getStartColumn(), se.getOriginalMessage(),
                        ScriptValidationError.SEVERITY_ERROR));
            } else if (raw instanceof Message) {
                errors.add(new ScriptValidationError(-1, -1, raw.toString(), ScriptValidationError.SEVERITY_ERROR));
            }
        }

        if (errors.isEmpty()) {
            errors.add(new ScriptValidationError(-1, -1, e.getMessage(), ScriptValidationError.SEVERITY_ERROR));
        }

        return errors;
    }

    private static ScriptValidationError toError(final PolyglotException e) {
        SourceSection location = e.getSourceLocation();

        // For syntax errors raised by Context.parse(...) the top-level source location is frequently null; the
        // offending location is then carried on the (single) polyglot stack frame instead.
        if (location == null || !location.isAvailable()) {
            for (final PolyglotException.StackFrame frame : e.getPolyglotStackTrace()) {
                final SourceSection frameLocation = frame.getSourceLocation();
                if (frameLocation != null && frameLocation.isAvailable()) {
                    location = frameLocation;
                    break;
                }
            }
        }

        if (location != null && location.isAvailable()) {
            return new ScriptValidationError(location.getStartLine(), location.getStartColumn(), e.getMessage(),
                    ScriptValidationError.SEVERITY_ERROR);
        }

        // Last resort: many language messages embed the position as "<name>:line:col".
        final Matcher matcher = MESSAGE_LOCATION_PATTERN.matcher(e.getMessage() == null ? "" : e.getMessage());
        if (matcher.find()) {
            return new ScriptValidationError(Integer.parseInt(matcher.group(1)), Integer.parseInt(matcher.group(2)),
                    e.getMessage(), ScriptValidationError.SEVERITY_ERROR);
        }

        return new ScriptValidationError(-1, -1, e.getMessage(), ScriptValidationError.SEVERITY_ERROR);
    }
}
