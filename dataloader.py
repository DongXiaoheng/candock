import scipy.io as sio
import numpy as np
import h5py
import os
import time
import torch
import random
import dsp
import transformer
# import pyedflib
import mne

# CinC_Challenge_2018
def loadstages(dirpath):
    filepath = os.path.join(dirpath,os.path.basename(dirpath)+'-arousal.mat')
    mat=h5py.File(filepath,'r')
    # N3(S4+S3)->0  N2->1  N1->2  REM->3  W->4  UND->5
    #print(mat.keys())
    N3 = mat['data']['sleep_stages']['nonrem3'][0]
    N2 = mat['data']['sleep_stages']['nonrem2'][0]
    N1 = mat['data']['sleep_stages']['nonrem1'][0]
    REM = mat['data']['sleep_stages']['rem'][0]
    W = mat['data']['sleep_stages']['wake'][0]
    UND = mat['data']['sleep_stages']['undefined'][0]
    stages = N3*0 + N2*1 + N1*2 + REM*3 + W*4 + UND*5
    return stages

def loadsignals(dirpath,name):
    hea_path = os.path.join(dirpath,os.path.basename(dirpath)+'.hea')
    signal_path = os.path.join(dirpath,os.path.basename(dirpath)+'.mat')
    signal_names = []
    for i,line in enumerate(open(hea_path),0):
        if i!=0:
            line=line.strip()
            signal_names.append(line.split()[8])
    mat = sio.loadmat(signal_path)
    return mat['val'][signal_names.index(name)]

def trimdata(data,num):
    return data[:num*int(len(data)/num)]

def reducesample(data,mult):
    return data[::mult]

def loaddata(dirpath,signal_name,BID,filter = True):
    #load
    signals = loadsignals(dirpath,signal_name)
    if filter:
        signals = dsp.BPF(signals,200,0.2,50,mod = 'fir')
    stages = loadstages(dirpath)
    #resample
    signals = reducesample(signals,2)
    stages = reducesample(stages,2)
    #Balance individualized differences
    if BID == 'median':
        signals = (signals*10/(np.median(abs(signals))))
    elif BID == '5_95_th':
        tmp = np.sort(signals.reshape(-1))
        th_5 = tmp[int(0.05*len(tmp))]
        signals=transformer.Normalize(signals,1000,0,th_5)
    #trim
    signals = trimdata(signals,3000)
    stages = trimdata(stages,3000)
    #30s per lable
    signals = signals.reshape(-1,3000)
    stages = stages[::3000]
    #del UND
    stages_copy = stages.copy()
    cnt = 0
    for i in range(len(stages_copy)):
        if stages_copy[i] == 5 :
            signals = np.delete(signals,i-cnt,axis =0)
            stages = np.delete(stages,i-cnt,axis =0)
            cnt += 1
    # print(stages.shape,signals.shape)
    return signals.astype(np.float16),stages.astype(np.int16)

def loaddata_sleep_edf(opt,filedir,filenum,signal_name,BID):
    filenames = os.listdir(filedir)
    for filename in filenames:
        if str(filenum) in filename and 'Hypnogram' in filename:
            f_stage_name = filename
        if str(filenum) in filename and 'PSG' in filename:
            f_signal_name = filename
    # print(f_stage_name)

    raw_data= mne.io.read_raw_edf(os.path.join(filedir,f_signal_name),preload=True)
    raw_annot = mne.read_annotations(os.path.join(filedir,f_stage_name))
    eeg = raw_data.pick_channels([signal_name]).to_data_frame().values.T
    eeg = eeg.reshape(-1)

    raw_data.set_annotations(raw_annot, emit_warning=False)
    event_id = {'Sleep stage 4': 0,
                  'Sleep stage 3': 0,
                  'Sleep stage 2': 1,
                  'Sleep stage 1': 2,
                  'Sleep stage R': 3,
                  'Sleep stage W': 4,
                  'Sleep stage ?': 5,
                  'Movement time': 5}
    events, _ = mne.events_from_annotations(
        raw_data, event_id=event_id, chunk_duration=30.)

    stages = []
    signals =[]
    for i in range(len(events)-1):
        stages.append(events[i][2])
        signals.append(eeg[events[i][0]:events[i][0]+3000])
    stages=np.array(stages)
    signals=np.array(signals)

    # #select sleep time 
    if opt.select_sleep_time:
        if 'SC' in f_signal_name:
            signals = signals[np.clip(int(raw_annot[0]['duration'])//30-60,0,9999999):int(raw_annot[-2]['onset'])//30+60]
            stages = stages[np.clip(int(raw_annot[0]['duration'])//30-60,0,9999999):int(raw_annot[-2]['onset'])//30+60]

    stages_copy = stages.copy()
    cnt = 0
    for i in range(len(stages_copy)):
        if stages_copy[i] == 5 :
            signals = np.delete(signals,i-cnt,axis =0)
            stages = np.delete(stages,i-cnt,axis =0)
            cnt += 1
    print('shape:',signals.shape,stages.shape)

    if BID == 'median':
        signals = signals*10/np.median(np.abs(signals))
    elif BID == '5_95_th':
        tmp = np.sort(signals.reshape(-1))
        th_5 = tmp[int(0.05*len(tmp))]
        signals=transformer.Normalize(signals,1000,0,th_5)

    return signals.astype(np.float16),stages.astype(np.int16)


def loaddataset(opt,filedir,dataset_name = 'CinC_Challenge_2018',signal_name = 'C4-M1',num = 100 ,BID = 'median' ,shuffle = True):
    print('load dataset, please wait...')
    filenames = os.listdir(filedir)

    if shuffle:
        random.shuffle(filenames)

    if dataset_name == 'CinC_Challenge_2018':
        if num > len(filenames):
            num = len(filenames)
            print('num of dataset is:',num)
        for i,filename in enumerate(filenames[:num],0):

            try:
                signal,stage = loaddata(os.path.join(filedir,filename),signal_name,BID = BID)
                if i == 0:
                    signals =signal.copy()
                    stages =stage.copy()
                else:
                    signals=np.concatenate((signals, signal), axis=0)
                    stages=np.concatenate((stages, stage), axis=0)
            except Exception as e:
                print(filename,e)
    elif dataset_name in ['sleep-edfx','sleep-edf']:
        if num > 197:
            num = 197
        if dataset_name == 'sleep-edf':
            filenames = ['SC4002E0-PSG.edf','SC4012E0-PSG.edf','SC4102E0-PSG.edf','SC4112E0-PSG.edf',
            'ST7022J0-PSG.edf','ST7052J0-PSG.edf','ST7121J0-PSG.edf','ST7132J0-PSG.edf']
        
        cnt = 0
        for filename in filenames:
            if 'PSG' in filename:
                signal,stage = loaddata_sleep_edf(opt,filedir,filename[2:6],signal_name,BID)
                if cnt == 0:
                    signals =signal.copy()
                    stages =stage.copy()
                else:
                    signals=np.concatenate((signals, signal), axis=0)
                    stages=np.concatenate((stages, stage), axis=0)
                cnt += 1
                if cnt == num:
                    break
    # print(np.median(np.abs(signals)))
    return signals,stages