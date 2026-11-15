/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.crypto;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Arrays;
import java.util.Objects;

import javax.crypto.BadPaddingException;
import javax.crypto.Cipher;
import javax.crypto.IllegalBlockSizeException;

/** Authenticate before releasing plaintext; spill only ciphertext, never plaintext. */
final class AuthenticatedDecryptingStream extends InputStream {
    private static final int MEMORY_LIMIT = 65536;
    private final InputStream encrypted;
    private final Cipher verifier;
    private final Cipher reader;
    private final Path temporaryRoot;
    private InputStream verified;
    private byte[] verifiedBytes;
    private Path temporaryDirectory;
    private Path temporaryFile;
    private IOException failure;
    private boolean closed;

    AuthenticatedDecryptingStream(InputStream encrypted, Cipher verifier, Cipher reader) {
        this(encrypted,verifier,reader,Path.of(System.getProperty("java.io.tmpdir")));
    }

    AuthenticatedDecryptingStream(InputStream encrypted, Cipher verifier, Cipher reader, Path temporaryRoot) {
        this.encrypted=encrypted;this.verifier=verifier;this.reader=reader;this.temporaryRoot=temporaryRoot;
    }

    private static final class PrivateBuffer extends ByteArrayOutputStream {
        void clear() { Arrays.fill(this.buf,(byte)0);reset(); }
    }

    private void authenticate() throws IOException {
        if (this.closed) { throw new IOException("Decryption stream closed"); }
        if (this.failure!=null) { throw this.failure; }
        if (this.verified!=null) { return; }
        PrivateBuffer memory=new PrivateBuffer();
        OutputStream spool=null;
        byte[] input=new byte[8192];
        try {
            int count;
            while ((count=this.encrypted.read(input))!=-1) {
                if(count==0){continue;}
                if (spool==null && (long)memory.size()+count>MEMORY_LIMIT) {
                    this.temporaryDirectory=Files.createTempDirectory(this.temporaryRoot,".kura-auth-",
                            PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
                    this.temporaryFile=Files.createFile(this.temporaryDirectory.resolve("value"),
                            PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
                    spool=Files.newOutputStream(this.temporaryFile,StandardOpenOption.WRITE);
                    memory.writeTo(spool);memory.clear();
                }
                if(spool==null){memory.write(input,0,count);}else{spool.write(input,0,count);}
                byte[] discard=this.verifier.update(input,0,count);
                if(discard!=null){Arrays.fill(discard,(byte)0);}
            }
            byte[] discard=this.verifier.doFinal();
            Arrays.fill(discard,(byte)0);
            InputStream ciphertext;
            if(spool!=null){
                spool.close();spool=null;
                ciphertext=Files.newInputStream(this.temporaryFile);
            }else{
                this.verifiedBytes=memory.toByteArray();
                ciphertext=new ByteArrayInputStream(this.verifiedBytes);
            }
            this.verified=new CheckedCipherStream(ciphertext,this.reader);
        }catch(BadPaddingException | IllegalBlockSizeException e){
            this.failure=new IOException("Ciphertext authentication failed");throw this.failure;
        }catch(IOException | RuntimeException e){
            this.failure=new IOException("Cannot authenticate ciphertext stream");throw this.failure;
        }finally{
            Arrays.fill(input,(byte)0);memory.clear();
            try{
                if(spool!=null){spool.close();}
            }finally{
                if(this.verified==null){cleanupTemporary();}
            }
        }
    }

    private void cleanupTemporary() throws IOException {
        if(this.temporaryFile!=null){Files.deleteIfExists(this.temporaryFile);this.temporaryFile=null;}
        if(this.temporaryDirectory!=null){Files.deleteIfExists(this.temporaryDirectory);this.temporaryDirectory=null;}
        if(this.verifiedBytes!=null){Arrays.fill(this.verifiedBytes,(byte)0);this.verifiedBytes=null;}
    }

    @Override public int read() throws IOException { authenticate();return this.verified.read(); }
    @Override public int read(byte[] bytes,int offset,int length) throws IOException {
        Objects.checkFromIndexSize(offset,length,bytes.length);
        if(length==0){return 0;}
        authenticate();return this.verified.read(bytes,offset,length);
    }
    @Override public int available() throws IOException {
        if(this.closed){throw new IOException("Decryption stream closed");}
        return this.verified==null?0:this.verified.available();
    }
    @Override public void close() throws IOException {
        if(this.closed){return;}this.closed=true;
        try{if(this.verified!=null){this.verified.close();}}
        finally{try{this.encrypted.close();}finally{cleanupTemporary();}}
    }

    /** Explicit finalization errors, including on the immutable verified second pass. */
    private static final class CheckedCipherStream extends InputStream {
        private final InputStream input;
        private final Cipher cipher;
        private final byte[] encrypted=new byte[8192];
        private byte[] plaintext=new byte[0];
        private int position;
        private boolean finished;
        private boolean closed;
        private IOException failure;
        CheckedCipherStream(InputStream input,Cipher cipher){this.input=input;this.cipher=cipher;}
        private boolean ready() throws IOException {
            if(this.closed){throw new IOException("Decryption stream closed");}
            if(this.failure!=null){throw this.failure;}
            while(this.position==this.plaintext.length){
                Arrays.fill(this.plaintext,(byte)0);this.position=0;
                if(this.finished){return false;}
                try{
                    int count=this.input.read(this.encrypted);
                    if(count<0){this.finished=true;this.plaintext=this.cipher.doFinal();}
                    else if(count>0){this.plaintext=this.cipher.update(this.encrypted,0,count);}
                    if(this.plaintext==null){this.plaintext=new byte[0];}
                }catch(BadPaddingException | IllegalBlockSizeException | RuntimeException e){
                    this.failure=new IOException("Ciphertext authentication failed");throw this.failure;
                }catch(IOException e){this.failure=e;throw e;}
            }
            return true;
        }
        @Override public int read() throws IOException {return ready()?Byte.toUnsignedInt(this.plaintext[this.position++]):-1;}
        @Override public int read(byte[] bytes,int offset,int length) throws IOException {
            Objects.checkFromIndexSize(offset,length,bytes.length);if(length==0){return 0;}
            if(!ready()){return -1;}int count=Math.min(length,this.plaintext.length-this.position);
            System.arraycopy(this.plaintext,this.position,bytes,offset,count);this.position+=count;return count;
        }
        @Override public void close() throws IOException {
            if(this.closed){return;}this.closed=true;
            Arrays.fill(this.encrypted,(byte)0);Arrays.fill(this.plaintext,(byte)0);this.input.close();
        }
    }
}
