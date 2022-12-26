import threading
import time
from typing import Dict, List

class Inputs:
    def __init__(self) -> None:
        self.user_audio: Dict[int, List[bytes]] = {}
        self.first_timestamp: int = 0

    def add_input(self, vc_data):
        if not any(self.user_audio):
            self.user_audio[vc_data[0]] = [vc_data[2]]
            self.first_timestamp = vc_data[1]
            return

        if vc_data[0] in self.user_audio.keys():
            self.user_audio[vc_data[0]].append(vc_data[2])
        else:
            offset =  int((vc_data[1] - self.first_timestamp) / 20e-3)
            self.user_audio[vc_data[0]] = [b"\x00"*len(vc_data[2])] * offset + [vc_data[2]]
    
    def clear_inputs(self):
        self.user_audio.clear()
        self.first_timestamp = 0
    
    def max_length(self):
        return max([len(v) for v in self.user_audio.values()])

    def get_align_data(self):
        max_length = self.max_length()
        data = []
        for v in self.user_audio.values():
            filler = [b"\x00" * 3840] * (max_length - len(v))
            data.append(v + filler)
        return data


def pcm2raw(pcm: bytes, channel: int = 2):
    data_length = int(len(pcm) / 2)
    raw = [0] * data_length
    for i in range(data_length):
        raw[i] = int.from_bytes(
            pcm[2 * i : 2 * (i + 1)], "little", signed=True
        )
    return raw

def mix_sample(sample1, sample2):
    sample1 += 32768
    sample2 += 32768

    if sample1 < 32768 or sample2 < 32768:
        mixed = int(sample1 * sample2 / 32768)
    else:
        mixed = 2 * (sample1 + sample2) - int((sample1 * sample2) / 32768) - 65536
    
    if mixed == 65536:
        mixed = 65535
    mixed -= 32768

    return mixed

def raw2pcm(raw: List[int], bitlength: int = 2):
    sound_bytes = [sample.to_bytes(bitlength, 'little', signed=True) for sample in raw]
    return b"".join(sound_bytes)
    
def mix_rawsound(s1, s2):
    combine = [mix_sample(s2[i], val) for i, val in enumerate(s1)]
    return combine

class MixerManager(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True, name="MixerManager")
        self.inputs: Inputs = Inputs()
        self.sample_byte_length = int(16 / 8)
        self.channel = 2
        self.reciver_vc = None
        self._end_thread = threading.Event()

    def run(self):
        while not self._end_thread.is_set():
            time.sleep(500e-3)
            if not any(self.inputs.user_audio):
                continue

            audio_seq = []
            if len(self.inputs.user_audio) == 1:
                audio_seq = list(self.inputs.user_audio.values())[0]
                for audio in audio_seq:
                    self.reciver_vc.send_audio_packet(audio)

            else:
                d = self.inputs.get_align_data()
                
                for i in range(self.inputs.max_length()):
                    sample = []
                    for v in d:
                        if len(sample) == 0:
                            sample = pcm2raw(v[i])
                        else:
                            sample = mix_rawsound(sample, pcm2raw(v[i]))

                    self.reciver_vc.send_audio_packet(raw2pcm(sample))

            self.inputs.clear_inputs()
    
    def stop(self):
        while self.mixing:
            print(self.inputs.user_audio)
            time.sleep(0.1)
        
        self._end_thread.set()
    
    @property
    def mixing(self):
        return bool(self.inputs.user_audio)

    def add_vc_data(self, vc_data):
        self.inputs.add_input(vc_data)
