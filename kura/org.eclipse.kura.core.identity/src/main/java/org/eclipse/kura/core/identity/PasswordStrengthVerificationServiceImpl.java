/*******************************************************************************
 * Copyright (c) 2024, 2025 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 *******************************************************************************/
package org.eclipse.kura.core.identity;

import static java.util.Objects.nonNull;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import java.util.stream.Collectors;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.ConfigurableComponent;
import org.eclipse.kura.identity.PasswordStrengthRequirements;
import org.eclipse.kura.identity.PasswordStrengthVerificationService;
import org.eclipse.kura.util.validation.PasswordStrengthValidators;
import org.eclipse.kura.util.validation.Validator;
import org.eclipse.kura.util.validation.ValidatorOptions;

public class PasswordStrengthVerificationServiceImpl
        implements PasswordStrengthVerificationService, ConfigurableComponent {

    private AtomicReference<PasswordStrengthRequirements> requirements = null;

    public void activate(Map<String, Object> options) {
        this.requirements = new AtomicReference<>(buildPasswordStrengthRequirements(options));
    }

    public void updated(Map<String, Object> options) {
        this.requirements.set(buildPasswordStrengthRequirements(options));
    }

    @Override
    public PasswordStrengthRequirements getPasswordStrengthRequirements() {
        return this.requirements.get();
    }

    @Override
    public void checkPasswordStrength(char[] password) throws KuraException {
        final PasswordStrengthRequirements currentRequirements = getPasswordStrengthRequirements();

        ValidatorOptions validatorOptions = new ValidatorOptions(currentRequirements.getPasswordMinimumLength(),
                currentRequirements.digitsRequired(), currentRequirements.bothCasesRequired(),
                currentRequirements.specialCharactersRequired());

        final List<Validator<String>> validators = PasswordStrengthValidators.fromConfig(validatorOptions);

        final List<String> errors = new ArrayList<>();

        for (final Validator<String> validator : validators) {
            validator.validate(new String(password), errors::add);
        }

        if (!errors.isEmpty()) {
            throw new KuraException(KuraErrorCode.INVALID_PARAMETER, "Password strength requirements not satisfied: "
                    + errors.stream().collect(Collectors.joining("; ")));
        }
    }

    private static PasswordStrengthRequirements buildPasswordStrengthRequirements(final Map<String, Object> options) {
        return new PasswordStrengthRequirements(getInt(options, "new.password.min.length"),
                getBool(options, "new.password.require.digits"),
                getBool(options, "new.password.require.special.characters"),
                getBool(options, "new.password.require.both.cases"));
    }

    static boolean getBool(final Map<String, Object> options, String name) {
        boolean result = false;
        final Object resultRaw = options.getOrDefault(name, false);
        if (nonNull(resultRaw) && resultRaw instanceof Boolean) {
            result = (Boolean) resultRaw;
        }
        return result;
    }

    static int getInt(final Map<String, Object> options, String name) {
        int result = 0;
        final Object resultRaw = options.get(name);
        if (nonNull(resultRaw) && resultRaw instanceof Integer) {
            result = (Integer) resultRaw;
        }
        return result;
    }

}
