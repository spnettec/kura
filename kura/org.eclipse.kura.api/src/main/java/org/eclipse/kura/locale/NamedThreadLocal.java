package org.eclipse.kura.locale;

public class NamedThreadLocal<T> extends ThreadLocal<T> {

    private final String name;

    /**
     * Create a new NamedThreadLocal with the given name.
     *
     * @param name
     *            a descriptive name for this ThreadLocal
     */
    public NamedThreadLocal(String name) {
        if (name == null) {
            throw new IllegalArgumentException("Name must not be empty");
        }
        this.name = name;
    }

    @Override
    public String toString() {
        return this.name;
    }

}