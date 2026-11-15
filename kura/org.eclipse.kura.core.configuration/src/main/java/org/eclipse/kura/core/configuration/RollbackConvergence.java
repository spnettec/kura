/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import java.lang.reflect.Array;
import java.util.*;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.core.configuration.util.CollectionsUtil;
import org.eclipse.kura.crypto.CryptoService;
import org.osgi.framework.Constants;
import org.osgi.service.cm.ConfigurationAdmin;

/** Detached public expectations and CM storage values for an accepted rollback. */
final class RollbackConvergence {
    private static final Set<String> IDENTITY = Set.of(ConfigurationService.KURA_SERVICE_PID, Constants.SERVICE_PID,
            ConfigurationAdmin.SERVICE_FACTORYPID, "service.bundleLocation", "component.id", "component.name");
    record Prepared(Map<String,Object> stored, RollbackConvergence convergence) { }
    private final Map<String,Object> required;
    private final Map<String,Object> optional;
    private final Map<String,Object> snapshot;
    private RollbackConvergence(Map<String,Object> required, Map<String,Object> optional, Map<String,Object> snapshot) {
        this.required=required; this.optional=optional; this.snapshot=snapshot;
    }
    static Prepared prepare(Map<String,Object> original, Map<String,Object> defaults,
            Set<String> passwordNames, CryptoService crypto) throws KuraException {
        Map<String,Object> stored=new HashMap<>(), required=new HashMap<>(), optional=new HashMap<>();
        for(var entry:defaults.entrySet()) {
            String key=key(entry.getKey());Object value=entry.getValue();
            if(secret(value)||passwordNames.contains(key)&&value!=null) {
                Object encoded=passwordShape(value,p->cipher(p,crypto,false));
                stored.put(key,encoded);optional.put(key,passwordShape(encoded,p->clear(p,crypto)));
            }else{stored.put(key,copy(value));optional.put(key,copy(value));}
        }
        for(var entry:original.entrySet()) {
            String key=key(entry.getKey());Object value=entry.getValue(), plain, encoded;
            if(secret(value)) {
                // Snapshot PASSWORD values have already been decrypted by the XML adapter.
                plain=copy(value);encoded=passwordShape(value,p->encrypt(p,crypto));
            }else if(passwordNames.contains(key)&&value!=null) {
                // Legacy STRING-typed password entries are accepted only as authenticated CM ciphertext.
                encoded=passwordShape(value,p->cipher(p,crypto,true));plain=passwordShape(encoded,p->clear(p,crypto));
            }else{plain=copy(value);encoded=copy(value);}
            stored.put(key,encoded);required.put(key,plain);optional.remove(key);
        }
        Map<String,Object> snapshot = new HashMap<>();
        optional.forEach((key,value)->snapshot.put(key,copy(value)));
        required.forEach((key,value)->snapshot.put(key,copy(value)));
        IDENTITY.forEach(required::remove);IDENTITY.forEach(optional::remove);
        // Finish dictionary conversion before any owner/CM mutation, including invalid password shapes.
        CollectionsUtil.mapToDictionary(stored);
        return new Prepared(stored,new RollbackConvergence(required,optional,snapshot));
    }
    Map<String,Object> snapshotProperties() {
        Map<String,Object> result = new HashMap<>();
        this.snapshot.forEach((key,value)->result.put(key,copy(value)));
        return result;
    }
    boolean matches(Map<String,Object> current) {
        if(current==null)return false;
        for(var entry:required.entrySet())if(!ConfigurationRevision.sameValue(entry.getValue(),current.get(entry.getKey())))return false;
        for(var entry:current.entrySet()) {
            String key=entry.getKey();if(key==null)return false;
            if(IDENTITY.contains(key)||required.containsKey(key)||entry.getValue()==null)continue;
            if(!optional.containsKey(key)||!ConfigurationRevision.sameValue(optional.get(key),entry.getValue()))return false;
        }
        return true;
    }
    private static String key(String key)throws KuraException {
        if(key==null)throw invalid();return key;
    }
    static boolean secret(Object value) {
        return value instanceof Password||value instanceof Password[]
                ||value instanceof Collection<?> collection&&collection.stream().anyMatch(Password.class::isInstance);
    }
    @FunctionalInterface private interface PasswordTransform { Password apply(Password value)throws KuraException; }
    private static Object passwordShape(Object value,PasswordTransform transform)throws KuraException {
        if(value instanceof Password password)return transform.apply(password);
        if(value instanceof String string)return transform.apply(new Password(string));
        if(value!=null&&value.getClass().isArray()) {
            if(value.getClass().getComponentType()!=Password.class&&value.getClass().getComponentType()!=String.class)throw invalid();
            int length=Array.getLength(value);Password[] result=new Password[length];
            for(int i=0;i<length;i++) {Object item=Array.get(value,i);if(item==null)throw invalid();result[i]=(Password)passwordShape(item,transform);}
            return result;
        }
        if(value instanceof Collection<?> collection) {
            Collection<Object> result=CollectionsUtil.newCollectionLike(collection);
            for(Object item:collection) {if(!(item instanceof Password||item instanceof String))throw invalid();result.add(passwordShape(item,transform));}
            return result;
        }
        throw invalid();
    }
    private static Password encrypt(Password password,CryptoService crypto)throws KuraException {
        if(crypto==null||password.getPassword()==null)throw invalid();
        char[] encrypted=crypto.encryptAes(password.getPassword().clone());
        if(encrypted==null||encrypted.length==0)throw invalid();return new Password(encrypted);
    }
    private static Password cipher(Password password,CryptoService crypto,boolean legacyEmpty)throws KuraException {
        if(password.getPassword()==null)throw invalid();
        if(password.getPassword().length==0) {if(legacyEmpty)return encrypt(password,crypto);throw invalid();}
        clear(password,crypto);return new Password(password.getPassword().clone());
    }
    private static Password clear(Password password,CryptoService crypto)throws KuraException {
        if(crypto==null||password.getPassword()==null||password.getPassword().length==0)throw invalid();
        char[] plain=crypto.decryptAes(password.getPassword().clone());if(plain==null)throw invalid();return new Password(plain);
    }
    static Object copy(Object value) {
        if(value instanceof Password password)return new Password(password.getPassword()==null?null:password.getPassword().clone());
        if(value!=null&&value.getClass().isArray()) {
            int length=Array.getLength(value);Object result=Array.newInstance(value.getClass().getComponentType(),length);
            for(int i=0;i<length;i++)Array.set(result,i,copy(Array.get(value,i)));return result;
        }
        if(value instanceof Collection<?> collection) {Collection<Object> result=CollectionsUtil.newCollectionLike(collection);for(Object item:collection)result.add(copy(item));return result;}
        return value;
    }
    private static KuraException invalid(){return new KuraException(KuraErrorCode.CONFIGURATION_ERROR,"Invalid rollback password representation");}
}
