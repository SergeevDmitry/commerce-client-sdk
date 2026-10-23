import {readFileSync} from 'node:fs';
import {createSigner} from '../packages/typescript/dist/signing.js';
const {privateKey,request}=JSON.parse(readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(await createSigner({keyId:'test-key',privateKey})(request)));
