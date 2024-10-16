package org.eclipse.kura.locale;

import java.util.Locale;
import java.util.TimeZone;

import org.eclipse.kura.annotation.Nullable;

public final class LocaleContextHolder {

    private static final ThreadLocal<LocaleContext> LOCALECONTEXTHOLDER = new NamedThreadLocal<>("LocaleContext");

    private static final ThreadLocal<LocaleContext> INHERITABLELOCALECONTEXTHOLDER = new NamedInheritableThreadLocal<>(
            "LocaleContext");

    // Shared default locale at the framework level
    @Nullable
    private static Locale defaultLocale;

    // Shared default time zone at the framework level
    @Nullable
    private static TimeZone defaultTimeZone;

    private LocaleContextHolder() {
    }

    /**
     * Reset the LocaleContext for the current thread.
     */
    public static void resetLocaleContext() {
        LOCALECONTEXTHOLDER.remove();
        INHERITABLELOCALECONTEXTHOLDER.remove();
    }

    /**
     * Associate the given LocaleContext with the current thread,
     * <i>not</i> exposing it as inheritable for child threads.
     * <p>
     * The given LocaleContext may be a {@link TimeZoneAwareLocaleContext},
     * containing a locale with associated time zone information.
     *
     * @param localeContext
     *            the current LocaleContext,
     *            or {@code null} to reset the thread-bound context
     * @see SimpleLocaleContext
     * @see SimpleTimeZoneAwareLocaleContext
     */
    public static void setLocaleContext(@Nullable LocaleContext localeContext) {
        setLocaleContext(localeContext, false);
    }

    /**
     * Associate the given LocaleContext with the current thread.
     * <p>
     * The given LocaleContext may be a {@link TimeZoneAwareLocaleContext},
     * containing a locale with associated time zone information.
     *
     * @param localeContext
     *            the current LocaleContext,
     *            or {@code null} to reset the thread-bound context
     * @param inheritable
     *            whether to expose the LocaleContext as inheritable
     *            for child threads (using an {@link InheritableThreadLocal})
     * @see SimpleLocaleContext
     * @see SimpleTimeZoneAwareLocaleContext
     */
    public static void setLocaleContext(@Nullable LocaleContext localeContext, boolean inheritable) {
        if (localeContext == null) {
            resetLocaleContext();
        } else {
            if (inheritable) {
                INHERITABLELOCALECONTEXTHOLDER.set(localeContext);
                LOCALECONTEXTHOLDER.remove();
            } else {
                LOCALECONTEXTHOLDER.set(localeContext);
                INHERITABLELOCALECONTEXTHOLDER.remove();
            }
        }
    }

    /**
     * Return the LocaleContext associated with the current thread, if any.
     *
     * @return the current LocaleContext, or {@code null} if none
     */
    @Nullable
    public static LocaleContext getLocaleContext() {
        LocaleContext localeContext = LOCALECONTEXTHOLDER.get();
        if (localeContext == null) {
            localeContext = INHERITABLELOCALECONTEXTHOLDER.get();
        }
        return localeContext;
    }

    /**
     * Associate the given Locale with the current thread,
     * preserving any TimeZone that may have been set already.
     * <p>
     * Will implicitly create a LocaleContext for the given Locale,
     * <i>not</i> exposing it as inheritable for child threads.
     *
     * @param locale
     *            the current Locale, or {@code null} to reset
     *            the locale part of thread-bound context
     * @see #setTimeZone(TimeZone)
     * @see SimpleLocaleContext#SimpleLocaleContext(Locale)
     */
    public static void setLocale(@Nullable Locale locale) {
        setLocale(locale, false);
    }

    /**
     * Associate the given Locale with the current thread,
     * preserving any TimeZone that may have been set already.
     * <p>
     * Will implicitly create a LocaleContext for the given Locale.
     *
     * @param locale
     *            the current Locale, or {@code null} to reset
     *            the locale part of thread-bound context
     * @param inheritable
     *            whether to expose the LocaleContext as inheritable
     *            for child threads (using an {@link InheritableThreadLocal})
     * @see #setTimeZone(TimeZone, boolean)
     * @see SimpleLocaleContext#SimpleLocaleContext(Locale)
     */
    public static void setLocale(@Nullable Locale locale, boolean inheritable) {
        LocaleContext localeContext = getLocaleContext();
        TimeZone timeZone = localeContext instanceof TimeZoneAwareLocaleContext
                ? ((TimeZoneAwareLocaleContext) localeContext).getTimeZone()
                : null;
        if (timeZone != null) {
            localeContext = new SimpleTimeZoneAwareLocaleContext(locale, timeZone);
        } else if (locale != null) {
            localeContext = new SimpleLocaleContext(locale);
        } else {
            localeContext = null;
        }
        setLocaleContext(localeContext, inheritable);
    }

    /**
     * Set a shared default locale at the framework level,
     * as an alternative to the JVM-wide default locale.
     * <p>
     * <b>NOTE:</b> This can be useful to set an application-level
     * default locale which differs from the JVM-wide default locale.
     * However, this requires each such application to operate against
     * locally deployed Spring Framework jars. Do not deploy Spring
     * as a shared library at the server level in such a scenario!
     *
     * @param locale
     *            the default locale (or {@code null} for none,
     *            letting lookups fall back to {@link Locale#getDefault()})
     * @since 4.3.5
     * @see #getLocale()
     * @see Locale#getDefault()
     */
    public static void setDefaultLocale(@Nullable Locale locale) {
        LocaleContextHolder.defaultLocale = locale;
    }

    /**
     * Return the Locale associated with the current thread, if any,
     * or the system default Locale otherwise. This is effectively a
     * replacement for {@link java.util.Locale#getDefault()},
     * able to optionally respect a user-level Locale setting.
     * <p>
     * Note: This method has a fallback to the shared default Locale,
     * either at the framework level or at the JVM-wide system level.
     * If you'd like to check for the raw LocaleContext content
     * (which may indicate no specific locale through {@code null}, use
     * {@link #getLocaleContext()} and call {@link LocaleContext#getLocale()}
     *
     * @return the current Locale, or the system default Locale if no
     *         specific Locale has been associated with the current thread
     * @see #getLocaleContext()
     * @see LocaleContext#getLocale()
     * @see #setDefaultLocale(Locale)
     * @see java.util.Locale#getDefault()
     */
    public static Locale getLocale() {
        return getLocale(getLocaleContext());
    }

    /**
     * Return the Locale associated with the given user context, if any,
     * or the system default Locale otherwise. This is effectively a
     * replacement for {@link java.util.Locale#getDefault()},
     * able to optionally respect a user-level Locale setting.
     *
     * @param localeContext
     *            the user-level locale context to check
     * @return the current Locale, or the system default Locale if no
     *         specific Locale has been associated with the current thread
     * @since 5.0
     * @see #getLocale()
     * @see LocaleContext#getLocale()
     * @see #setDefaultLocale(Locale)
     * @see java.util.Locale#getDefault()
     */
    public static Locale getLocale(@Nullable LocaleContext localeContext) {
        if (localeContext != null) {
            Locale locale = localeContext.getLocale();
            if (locale != null) {
                return locale;
            }
        }
        return defaultLocale != null ? defaultLocale : Locale.getDefault();
    }

    /**
     * Associate the given TimeZone with the current thread,
     * preserving any Locale that may have been set already.
     * <p>
     * Will implicitly create a LocaleContext for the given Locale,
     * <i>not</i> exposing it as inheritable for child threads.
     *
     * @param timeZone
     *            the current TimeZone, or {@code null} to reset
     *            the time zone part of the thread-bound context
     * @see #setLocale(Locale)
     * @see SimpleTimeZoneAwareLocaleContext#SimpleTimeZoneAwareLocaleContext(Locale, TimeZone)
     */
    public static void setTimeZone(@Nullable TimeZone timeZone) {
        setTimeZone(timeZone, false);
    }

    /**
     * Associate the given TimeZone with the current thread,
     * preserving any Locale that may have been set already.
     * <p>
     * Will implicitly create a LocaleContext for the given Locale.
     *
     * @param timeZone
     *            the current TimeZone, or {@code null} to reset
     *            the time zone part of the thread-bound context
     * @param inheritable
     *            whether to expose the LocaleContext as inheritable
     *            for child threads (using an {@link InheritableThreadLocal})
     * @see #setLocale(Locale, boolean)
     * @see SimpleTimeZoneAwareLocaleContext#SimpleTimeZoneAwareLocaleContext(Locale, TimeZone)
     */
    public static void setTimeZone(@Nullable TimeZone timeZone, boolean inheritable) {
        LocaleContext localeContext = getLocaleContext();
        Locale locale = localeContext != null ? localeContext.getLocale() : null;
        if (timeZone != null) {
            localeContext = new SimpleTimeZoneAwareLocaleContext(locale, timeZone);
        } else if (locale != null) {
            localeContext = new SimpleLocaleContext(locale);
        } else {
            localeContext = null;
        }
        setLocaleContext(localeContext, inheritable);
    }

    /**
     * Set a shared default time zone at the framework level,
     * as an alternative to the JVM-wide default time zone.
     * <p>
     * <b>NOTE:</b> This can be useful to set an application-level
     * default time zone which differs from the JVM-wide default time zone.
     * However, this requires each such application to operate against
     * locally deployed Spring Framework jars. Do not deploy Spring
     * as a shared library at the server level in such a scenario!
     *
     * @param timeZone
     *            the default time zone (or {@code null} for none,
     *            letting lookups fall back to {@link TimeZone#getDefault()})
     * @since 4.3.5
     * @see #getTimeZone()
     * @see TimeZone#getDefault()
     */
    public static void setDefaultTimeZone(@Nullable TimeZone timeZone) {
        defaultTimeZone = timeZone;
    }

    /**
     * Return the TimeZone associated with the current thread, if any,
     * or the system default TimeZone otherwise. This is effectively a
     * replacement for {@link java.util.TimeZone#getDefault()},
     * able to optionally respect a user-level TimeZone setting.
     * <p>
     * Note: This method has a fallback to the shared default TimeZone,
     * either at the framework level or at the JVM-wide system level.
     * If you'd like to check for the raw LocaleContext content
     * (which may indicate no specific time zone through {@code null}, use
     * {@link #getLocaleContext()} and call {@link TimeZoneAwareLocaleContext#getTimeZone()}
     * after downcasting to {@link TimeZoneAwareLocaleContext}.
     *
     * @return the current TimeZone, or the system default TimeZone if no
     *         specific TimeZone has been associated with the current thread
     * @see #getLocaleContext()
     * @see TimeZoneAwareLocaleContext#getTimeZone()
     * @see #setDefaultTimeZone(TimeZone)
     * @see java.util.TimeZone#getDefault()
     */
    public static TimeZone getTimeZone() {
        return getTimeZone(getLocaleContext());
    }

    /**
     * Return the TimeZone associated with the given user context, if any,
     * or the system default TimeZone otherwise. This is effectively a
     * replacement for {@link java.util.TimeZone#getDefault()},
     * able to optionally respect a user-level TimeZone setting.
     *
     * @param localeContext
     *            the user-level locale context to check
     * @return the current TimeZone, or the system default TimeZone if no
     *         specific TimeZone has been associated with the current thread
     * @since 5.0
     * @see #getTimeZone()
     * @see TimeZoneAwareLocaleContext#getTimeZone()
     * @see #setDefaultTimeZone(TimeZone)
     * @see java.util.TimeZone#getDefault()
     */
    public static TimeZone getTimeZone(@Nullable LocaleContext localeContext) {
        if (localeContext instanceof TimeZoneAwareLocaleContext) {
            TimeZone timeZone = ((TimeZoneAwareLocaleContext) localeContext).getTimeZone();
            if (timeZone != null) {
                return timeZone;
            }
        }
        return defaultTimeZone != null ? defaultTimeZone : TimeZone.getDefault();
    }

}