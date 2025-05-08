<template>
    <div>
        <li  v-if="file==null && !sampleLoaded" >
            <a @click="onLoadSample('sample')" class="section"><i class="fas fa-play"></i>  Open Sample </a>
        </li>
        <li v-if="url">
            <a @click="share" class="section"><i class="fas fa-share-alt"></i> {{ shared ? 'Copied to clipboard!' :
                'Share link'}}</a>
        </li>
        <li v-if="url">
            <a :href="'/uploaded/' + url" class="section" target="_blank"><i class="fas fa-download"></i> Download</a>
        </li>
        <div @click="browse" @dragover.prevent @drop="onDrop" id="drop_zone"
        v-if="file==null && uploadpercentage===-1  && !sampleLoaded">
            <p>Drop *.tlog or *.bin file here or click to browse</p>
            <input @change="onChange" id="choosefile" style="opacity: 0;" type="file">
        </div>
        <!--<b-form-checkbox @change="uploadFile()" class="uploadCheckbox" v-if="file!=null && !uploadStarted"> Upload
        </b-form-checkbox>-->
        <VProgress v-bind:complete="transferMessage"
                   v-bind:percent="uploadpercentage"
                   v-if="uploadpercentage > -1">
        </VProgress>
        <VProgress v-bind:complete="state.processStatus"
                   v-bind:percent="state.processPercentage"
                   v-if="state.processPercentage > -1"
        ></VProgress>
    </div>
</template>
<script>
/* eslint-disable */
import VProgress from './SideBarFileManagerProgressBar.vue'
import Worker from '../tools/parsers/parser.worker.js'
import { store } from './Globals'
import axios from 'axios'

import { MAVLink20Processor as MAVLink } from '../libs/mavlink'

const worker = new Worker()

worker.addEventListener('message', function (event) {
})

export default {
    name: 'Dropzone',
    data: function () {
        return {
            // eslint-disable-next-line no-undef
            mavlinkParser: new MAVLink(),
            uploadpercentage: -1,
            sampleLoaded: false,
            shared: false,
            url: null,
            transferMessage: '',
            state: store,
            file: null,
            uploadStarted: false
        }
    },
    created () {
        this.$eventHub.$on('loadType', this.loadType)
        this.$eventHub.$on('trimFile', this.trimFile)
    },
    beforeDestroy () {
        this.$eventHub.$off('open-sample')
    },
    methods: {
        trimFile () {
            worker.postMessage({ action: 'trimFile', time: this.state.timeRange })
        },
        onLoadSample (file) {
            let url
            if (file === 'sample') {
                this.state.file = 'sample.tlog' // Give a more specific name
                url = require('../assets/vtol.tlog').default
                this.state.logType = 'tlog'
            } else {
                // Assuming 'file' here is a URL string if not 'sample'
                url = file
                this.state.file = url.substring(url.lastIndexOf('/') + 1) // Extract filename
            }

            this.uploadpercentage = 0
            this.transferMessage = 'Downloading sample...'
            this.sampleLoaded = false // Reset while loading new sample

            const oReq = new XMLHttpRequest()
            console.log(`loading file from ${url}`)
            // this.state.logType is already set above for sample, or will be set by extension for direct URL
            if (url.includes('.tlog')) this.state.logType = 'tlog'
            else if (url.includes('.bin')) this.state.logType = 'bin'
            // Add other types if necessary

            oReq.open('GET', url, true)
            oReq.responseType = 'arraybuffer'

            oReq.onload = async (oEvent) => { // Use arrow function for `this` context and async for await
                const arrayBuffer = oReq.response
                if (arrayBuffer) {
                    this.transferMessage = 'Download complete. Uploading to server...'
                    this.uploadpercentage = 0 // Reset for upload progress

                    const blob = new Blob([arrayBuffer])
                    const fileToUpload = new File([blob], this.state.file, { type: blob.type || 'application/octet-stream' })
                    const formData = new FormData()
                    formData.append('file', fileToUpload)

                    try {
                        const response = await axios.post(`${this.state.backendApiUrl}/api/upload_log/`, formData, {
                            onUploadProgress: (progressEvent) => {
                                if (progressEvent.lengthComputable) {
                                    this.uploadpercentage = Math.round((progressEvent.loaded * 100) / progressEvent.total)
                                }
                            }
                        })
                        this.transferMessage = 'Server processing complete!'
                        this.uploadpercentage = 100
                        this.sampleLoaded = true
                        this.state.processStatus = 'Log uploaded. Ready for chat.'
                        this.state.processPercentage = 100
                        this.state.processDone = true
                        console.log('Backend upload response (sample):', response.data)
                        // Client-side worker parsing can still happen if needed for immediate UI features
                        // not dependent on backend's full analysis for chat.
                        worker.postMessage({ action: 'parse', file: arrayBuffer, isTlog: (this.state.logType === 'tlog'), isDji: (this.state.logType === 'dji') })
                    } catch (error) {
                        this.transferMessage = 'Error uploading sample to server.'
                        this.uploadpercentage = 100 // Show completion of attempt
                        console.error('Error uploading sample to backend:', error)
                        alert('Error uploading sample to server. Check console.')
                    }
                }
            }
            oReq.addEventListener('progress', (e) => {
                if (e.lengthComputable) {
                    this.uploadpercentage = Math.round((e.loaded * 100) / e.total)
                    this.transferMessage = `Downloading: ${this.uploadpercentage}%`
                }
            }
            , false)
            oReq.onerror = (error) => {
                alert('unable to fetch remote file, check CORS settings in the target server')
                console.log(error)
            }

            oReq.send()
        },
        onChange (ev) {
            const fileinput = document.getElementById('choosefile')
            this.process(fileinput.files[0])
        },
        onDrop (ev) {
            // Prevent default behavior (Prevent file from being opened)
            ev.preventDefault()
            if (ev.dataTransfer.items) {
                // Use DataTransferItemList interface to access the file(s)
                for (let i = 0; i < ev.dataTransfer.items.length; i++) {
                    // If dropped items aren't files, reject them
                    if (ev.dataTransfer.items[i].kind === 'file') {
                        const file = ev.dataTransfer.items[i].getAsFile()
                        this.process(file)
                    }
                }
            } else {
                // Use DataTransfer interface to access the file(s)
                for (let i = 0; i < ev.dataTransfer.files.length; i++) {
                    console.log('... file[' + i + '].name = ' + ev.dataTransfer.files[i].name)
                    console.log(ev.dataTransfer.files[i])
                }
            }
        },
        loadType: function (type) {
            worker.postMessage({
                action: 'loadType',
                type: type
            })
        },
        process: function (file) {
            this.state.file = file.name
            this.state.processStatus = 'Pre-processing...'
            this.state.processPercentage = 100
            this.file = file
            const reader = new FileReader()
            reader.onload = function (e) {
                const data = reader.result
                worker.postMessage({
                    action: 'parse',
                    file: data,
                    isTlog: (file.name.endsWith('tlog')),
                    isDji: (file.name.endsWith('txt'))
                })
            }
            this.state.logType = file.name.endsWith('tlog') ? 'tlog' : 'bin'
            if (file.name.endsWith('.txt')) {
                this.state.logType = 'dji'
            }
            reader.readAsArrayBuffer(file)

            // --- Add backend upload logic here ---
            this.uploadpercentage = 0
            this.transferMessage = 'Preparing to upload...'
            const formDataToUpload = new FormData()
            formDataToUpload.append('file', file) // Use the original 'file' object from input/drop

            axios.post(`${this.state.backendApiUrl}/api/upload_log/`, formDataToUpload, {
                onUploadProgress: (progressEvent) => {
                    if (progressEvent.lengthComputable) {
                        this.uploadpercentage = Math.round((progressEvent.loaded * 100) / progressEvent.total)
                        this.transferMessage = `Uploading: ${this.uploadpercentage}%`
                    }
                }
            }).then(response => {
                this.transferMessage = 'Server processing complete!'
                this.uploadpercentage = 100
                this.state.processStatus = 'Log uploaded. Ready for chat.'
                this.state.processPercentage = 100 // Assuming backend handles full processing
                this.state.processDone = true
                console.log('Backend upload response (local file):', response.data)
                // The original worker.postMessage for client-side parsing is still here.
                // Decide if it's still needed or if all parsing logic moves to backend.
            }).catch(error => {
                this.transferMessage = 'Error uploading file to server.'
                this.uploadpercentage = 100 // Show completion of attempt
                console.error('Error uploading local file to backend:', error)
                alert('Error uploading file to server. Check console.')
                // Reset processing state if backend upload fails
                this.state.processStatus = 'Upload failed'
                this.state.processPercentage = 0
                this.state.processDone = false
            })
            // --- End backend upload logic ---
        },
        // The original uploadFile method seems to be for a different endpoint or purpose.
        // I'm leaving it as is, as the request was to modify how samples and user-selected files
        // (handled by `process`) are uploaded to the FastAPI backend.
        // If this `uploadFile` method also needs to target the FastAPI endpoint,
        // it would need similar axios logic.
        uploadFile () { 
            this.uploadStarted = true
            this.transferMessage = 'Upload Done!'
            this.uploadpercentage = 0
            const formData = new FormData()
            formData.append('file', this.file)

            const request = new XMLHttpRequest()
            request.onload = () => {
                if (request.status >= 200 && request.status < 400) {
                    this.uploadpercentage = 100
                    this.url = request.responseText
                } else {
                    alert('error! ' + request.status)
                    this.uploadpercentage = 100
                    this.transferMessage = 'Error Uploading'
                    console.log(request)
                }
            }
            request.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable) {
                    this.uploadpercentage = 100 * e.loaded / e.total
                }
            }
            , false)
            request.open('POST', '/upload')
            request.send(formData)
        },
        fixData (message) {
            if (message.name === 'GLOBAL_POSITION_INT') {
                message.lat = message.lat / 10000000
                message.lon = message.lon / 10000000
                // eslint-disable-next-line
                message.relative_alt = message.relative_alt / 1000
            }
            return message
        },
        browse () {
            document.getElementById('choosefile').click()
        },
        share () {
            const el = document.createElement('textarea')
            el.value = window.location.host + '/#/v/' + this.url
            document.body.appendChild(el)
            el.select()
            document.execCommand('copy')
            document.body.removeChild(el)
            this.shared = true
        },
        downloadFileFromURL (url) {
            const a = document.createElement('a')
            document.body.appendChild(a)
            a.style = 'display: none'
            a.href = url
            a.download = this.state.file + '-trimmed.' + this.state.logType
            a.click()
            document.body.removeChild(a)
            window.URL.revokeObjectURL(url)
        }
    },
    mounted () {
        window.addEventListener('message', (event) => {
            if (event.data.type === 'arrayBuffer') {
                worker.postMessage({
                    action: 'parse',
                    file: event.data.data,
                    isTlog: false,
                    isDji: false
                })
            }
        })
        worker.onmessage = (event) => {
            if (event.data.percentage) {
                this.state.processPercentage = event.data.percentage
            } else if (event.data.availableMessages) {
                this.$eventHub.$emit('messageTypes', event.data.availableMessages)
            } else if (event.data.metadata) {
                this.state.metadata = event.data.metadata
            } else if (event.data.messages) {
                this.state.messages = event.data.messages
                this.$eventHub.$emit('messages')
            } else if (event.data.messagesDoneLoading) {
                this.$eventHub.$emit('messagesDoneLoading')
            } else if (event.data.messageType) {
                this.state.messages[event.data.messageType] = event.data.messageList
                this.$eventHub.$emit('messages')
            } else if (event.data.files) {
                this.state.files = event.data.files
                this.$eventHub.$emit('messages')
            } else if (event.data.url) {
                this.downloadFileFromURL(event.data.url)
            }
        }
        const url = document.location.search.split('?file=')[1]
        if (url) {
            this.onLoadSample(url)
        }
    },
    components: {
        VProgress
    }
}
</script>
<style scoped>

    /* NAVBAR */

    #drop_zone {
        padding-top: 25px;
        padding-left: 10px;
        border: 2px dashed #434b52da;
        width: auto;
        height: 100px;
        margin: 20px;
        border-radius: 5px;
        cursor: default;
        background-color: rgba(0, 0, 0, 0);
    }

    #drop_zone:hover {
        background-color: #171e2450;
    }

    .uploadCheckbox {
        margin-left: 20px;
    }

</style>
