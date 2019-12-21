package org.eclipse.kura.locale;

import java.util.TimeZone;

import org.eclipse.kura.annotation.Nullable;

public interface TimeZoneAwareLocaleContext extends LocaleContext {

    /**
     * Return the current TimeZone, which can be fixed or determined dynamically,
     * depending on the implementation strategy.
     * 
     * @return the current TimeZone, or {@code null} if no specific TimeZone associated
     */
    @Nullable
    TimeZone getTimeZone();

}