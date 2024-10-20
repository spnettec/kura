/*******************************************************************************
 * Copyright (c) 2020, 2024 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.web.client.ui;

import static java.util.Objects.requireNonNull;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Optional;
import java.util.function.Consumer;
import java.util.function.Function;

import org.gwtbootstrap3.client.ui.Button;
import org.gwtbootstrap3.client.ui.FormLabel;
import org.gwtbootstrap3.client.ui.Input;
import org.gwtbootstrap3.client.ui.Modal;
import org.gwtbootstrap3.client.ui.Panel;
import org.gwtbootstrap3.client.ui.base.HasId;
import org.gwtbootstrap3.client.ui.form.error.BasicEditorError;
import org.gwtbootstrap3.client.ui.form.validator.Validator;

import com.google.gwt.core.client.GWT;
import com.google.gwt.editor.client.Editor;
import com.google.gwt.editor.client.EditorError;
import com.google.gwt.event.shared.HandlerRegistration;
import com.google.gwt.uibinder.client.UiBinder;
import com.google.gwt.uibinder.client.UiField;
import com.google.gwt.user.client.ui.Composite;
import com.google.gwt.user.client.ui.FormPanel;
import com.google.gwt.user.client.ui.Widget;

public class Picker extends Composite implements HasId {

    private static PickerUiBinder uiBinder = GWT.create(PickerUiBinder.class);

    interface PickerUiBinder extends UiBinder<Widget, Picker> {
    }

    @UiField
    FormLabel label;
    @UiField
    FormPanel form;
    @UiField
    Button yes;
    @UiField
    Button no;
    @UiField
    Panel inputPanel;

    private final Modal modal;

    private Optional<Consumer<State<?>>> dismissAction = Optional.empty();
    private Optional<State<?>> state = Optional.empty();

    public Picker() {
        this.modal = (Modal) uiBinder.createAndBindUi(this);
        initWidget(this.modal);

        this.modal.setHideOtherModals(false);

        this.yes.addClickHandler(e -> {
            this.dismissAction = Optional.of(State::onAccept);
            onHide();
        });
        this.no.addClickHandler(e -> onHide());
        this.modal.addHiddenHandler(e -> onHide());
    }

    public void onHide() {
        if (!this.state.isPresent()) {
            return;
        }

        final State<?> currentState = this.state.get();

        if (this.dismissAction.isPresent()) {
            final Consumer<State<?>> currentAction = this.dismissAction.get();
            this.dismissAction = Optional.empty();
            currentAction.accept(currentState);
        }
        if (this.state.isPresent() && this.state.get() == currentState) {
            this.modal.hide();
            this.state = Optional.empty();
        }
    }

    @Override
    public String getId() {
        return this.modal.getId();
    }

    @Override
    public void setId(final String id) {
        this.modal.setId(id);
    }

    public <U> Builder<U> builder(final Class<U> classz, final Function<String, U> provider) {
        return new Builder<>(provider);
    }

    public Builder<String> builder() {
        return new Builder<>(Function.identity());
    }

    public class Builder<U> {

        private List<Validator<String>> validators = Collections.emptyList();
        private final Function<String, U> provider;
        private Consumer<U> consumer;
        private String title;

        private Optional<String> message = Optional.empty();
        private Optional<Runnable> onCancel = Optional.empty();
        private Optional<Consumer<Input>> customizer = Optional.empty();

        public Builder(final Function<String, U> provider) {
            this.provider = provider;
        }

        public Builder<U> setTitle(final String title) {
            this.title = title;
            return this;
        }

        public Builder<U> setValidators(final List<Validator<String>> validators) {
            this.validators = validators;
            return this;
        }

        public Builder<U> setOnPick(final Consumer<U> consumer) {
            this.consumer = consumer;
            return this;
        }

        public Builder<U> setMessage(final String message) {
            this.message = Optional.of(message);
            return this;
        }

        public Builder<U> setOnCancel(final Runnable onCancel) {
            this.onCancel = Optional.of(onCancel);
            return this;
        }

        public Builder<U> setInputCustomizer(final Consumer<Input> customizer) {
            this.customizer = Optional.of(customizer);
            return this;
        }

        private Input initInput() {
            final Input result = new Input();
            result.addKeyUpHandler(e -> result.validate());
            if (this.customizer.isPresent()) {
                this.customizer.get().accept(result);
            }
            return result;
        }

        public void pick() {
            requireNonNull(this.provider, "provider cannot be null");
            requireNonNull(this.validators, "validators cannot be null");
            requireNonNull(this.consumer, "onPick cannot be null");
            requireNonNull(this.title, "title cannot be null");

            Picker.this.modal.setTitle(this.title);

            if (this.message.isPresent()) {
                Picker.this.label.setText(this.message.get());
            } else {
                Picker.this.label.setText("");
            }

            final Input input = initInput();

            final State<U> localState = new State<>(input, this.provider, this.validators, this.consumer,
                    this.onCancel.orElse(() -> {
                    }));

            Picker.this.state = Optional.of(localState);
            Picker.this.dismissAction = Optional.of(State::onCancel);

            Picker.this.inputPanel.add(input);

            input.validate();
            input.reset();
            Picker.this.modal.show();
        }
    }

    private class State<U> implements Validator<String> {

        private final Input value;
        private final Function<String, U> provider;
        private final List<Validator<String>> validators;
        private final Consumer<U> consumer;
        private final Runnable onDismiss;
        private final HandlerRegistration submitHandler;
        private final com.google.web.bindery.event.shared.HandlerRegistration shownHandler;

        private Optional<U> currentValue = Optional.empty();

        @SuppressWarnings("unchecked")
        public State(Input value, Function<String, U> provider, List<Validator<String>> validators,
                Consumer<U> consumer,
                final Runnable onCancel) {
            this.value = value;
            this.provider = provider;
            this.validators = validators;
            this.consumer = consumer;
            this.onDismiss = onCancel;
            this.value.setValidators(this);
            this.submitHandler = Picker.this.form.addSubmitHandler(e -> {
                e.cancel();
                if (value.validate()) {
                    Picker.this.dismissAction = Optional.of(State::onAccept);
                    Picker.this.modal.hide();
                }
            });
            this.shownHandler = Picker.this.modal.addShownHandler(e -> value.setFocus(true));
        }

        public void onAccept() {
            cleanup();
            if (this.currentValue.isPresent()) {
                this.consumer.accept(this.currentValue.get());
            }
        }

        public void onCancel() {
            cleanup();
            this.onDismiss.run();
        }

        private void cleanup() {
            Picker.this.inputPanel.clear();
            this.submitHandler.removeHandler();
            this.shownHandler.removeHandler();
        }

        @Override
        public int getPriority() {
            return 0;
        }

        @Override
        public List<EditorError> validate(Editor<String> editor, String valueString) {
            try {
                final List<EditorError> result = new ArrayList<>();

                for (final Validator<String> validator : this.validators) {
                    result.addAll(validator.validate(editor, valueString));
                }
                if (result.isEmpty()) {
                    this.currentValue = Optional.of(this.provider.apply(valueString));
                    Picker.this.yes.setEnabled(true);
                } else {
                    this.currentValue = Optional.empty();
                    Picker.this.yes.setEnabled(false);
                }
                return result;

            } catch (final Exception e) {
                return Collections.singletonList(new BasicEditorError(editor, valueString, e.getMessage()));
            }
        }
    }
}
