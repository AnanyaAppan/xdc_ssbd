import os
os.environ["CUDA_DEVICE_ORDER"]="PCI_BUS_ID"   
#os.environ["CUDA_VISIBLE_DEVICES"]='0,1,2,3'
import sys
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('-mode', type=str, help='rgb or flow')
parser.add_argument('-save_model', type=str)
parser.add_argument('-root', type=str)

args = parser.parse_args()

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.optim import lr_scheduler
from torch.autograd import Variable

import torchvision
from torchvision import datasets, transforms
import videotransforms
from collections import OrderedDict


import numpy as np

from charades_dataset import Charades as Dataset


def run(init_lr=0.1, max_steps=64e3, mode='rgb', root='../../SSBD/ssbd_clip_segment/data/', train_split='../../SSBD/Annotations/annotations_charades.json', batch_size=1, save_model=''):
    # setup dataset
    train_transforms = transforms.Compose([videotransforms.RandomCrop(224),
                                           videotransforms.RandomHorizontalFlip(),
    ])
    test_transforms = transforms.Compose([videotransforms.CenterCrop(224)])

    dataset = Dataset(train_split, 'training', root, mode, train_transforms)
    dataloader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True, num_workers=4, pin_memory=True)

    val_dataset = Dataset(train_split, 'testing', root, mode, test_transforms)
    val_dataloader = torch.utils.data.DataLoader(val_dataset, batch_size=batch_size, shuffle=True, num_workers=4, pin_memory=True)

    dataloaders = {'train': dataloader, 'val': val_dataloader}
    datasets = {'train': dataset,'val': val_dataset }

    # dataloaders = {'train': dataloader}
    # datasets = {'train': dataset}

    
    # setup the model

    xdc = torch.hub.load('HumamAlwassel/XDC', 'xdc_video_encoder', 
                        pretraining='r2plus1d_18_xdc_ig65m_kinetics',
                        num_classes=3)
    # if mode == 'flow':
    #     i3d = InceptionI3d(400, in_channels=2)
    #     i3d.load_state_dict(torch.load('models/flow_imagenet.pt'))
    # else:
    #     i3d = InceptionI3d(400, in_channels=3)
    #     i3d.load_state_dict(torch.load('models/rgb_imagenet.pt'))
    # i3d.replace_logits(8)
    # #i3d.load_state_dict(torch.load('/ssd/models/000920.pt'))
    # i3d.cuda()
    # i3d = nn.DataParallel(i3d)
    xdc.cuda()
    xdc = nn.DataParallel(xdc).cuda()

    for name, param in xdc.named_parameters():
        if 'fc' not in name or '4.1' not in name:
            param.requires_grad = False

    lr = init_lr
    optimizer = optim.SGD(xdc.parameters(), lr=lr, momentum=0.9, weight_decay=0.0000001)
    lr_sched = optim.lr_scheduler.MultiStepLR(optimizer, [300, 1000])


    num_steps_per_update = 4 # accum gradient
    steps = 0
    best_val = 0
    # new_flag = 0
    # train it
    while steps < max_steps:#for epoch in range(num_epochs):
        print('Step {}/{}'.format(steps, max_steps))
        print('-' * 10)
        # new_state_dict = OrderedDict()
        # state_dict = torch.load(save_model+'.pt')
        # for k, v in state_dict.items():
        #     name = "module."+k # add module.
        #     new_state_dict[name] = v
        # xdc.load_state_dict(new_state_dict)
        # new_flag = 0
        # Each epoch has a training and validation phase
        for phase in ['train','val']:
            if phase == 'train':
                xdc.train(True)
            else:
                xdc.train(False)  # Set model to evaluate mode
                
            tot_loss = 0.0
            # tot_loc_loss = 0.0
            # tot_cls_loss = 0.0
            num_iter = 0
            total = 0
            n = 0
            optimizer.zero_grad()
            
            # Iterate over data.
            for data in dataloaders[phase]:
                num_iter += 1
                # get the inputs
                inputs, labels = data

                # wrap them in Variable
                inputs = Variable(inputs.cuda())
                t = inputs.size(2)
                labels = Variable(labels.cuda())

                per_frame_logits = xdc(inputs)
                # print(per_frame_logits.shape)
                # print(labels.shape)
                # upsample to input size
                # per_frame_logits = F.upsample(per_frame_logits, t, mode='linear')

                # compute localization loss
                # loc_loss = F.binary_cross_entropy_with_logits(per_frame_logits, labels)
                # tot_loc_loss += loc_loss.data.item()

                # compute classification loss (with max-pooling along time B x C x T)
                # cls_loss = F.binary_cross_entropy_with_logits(torch.max(per_frame_logits, dim=2)[0], torch.max(labels, dim=2)[0])
                # print(torch.max(per_frame_logits, dim=2)[0])
                # print(torch.max(labels, dim=2)[0])
                correct = per_frame_logits.argmax(1).eq(labels.argmax(1))
                total += correct.float().sum().item() 
                n += batch_size
                # tot_cls_loss += cls_loss.data.item()

                loss = F.binary_cross_entropy_with_logits(per_frame_logits,labels)/num_steps_per_update
                tot_loss += loss.data.item()
                loss.backward()

                if num_iter == num_steps_per_update and phase == 'train':
                    steps += 1
                    num_iter = 0
                    optimizer.step()
                    optimizer.zero_grad()
                    lr_sched.step()
                    if steps % 10 == 0:
                        print('{} Tot Loss: {:.4f} Accuracy: {:.4f}'.format(phase, tot_loss/10, total/n))
                        # save model
                        # if(steps % 10000 == 0):
                            # torch.save(xdc.module.state_dict(), save_model+str(steps).zfill(6)+'.pt')
                        # tot_loss = tot_loc_loss = tot_cls_loss = 0.
                        tot_loss = 0
                        total = 0
                        n = 0
            if phase == 'val':
                print('{} Tot Loss: {:.4f} Accuracy: {:.4f}'.format(phase, (tot_loss*num_steps_per_update)/num_iter, total/n))
                if(total/n > best_val):
                    best_val = total/n
                    torch.save(xdc.module.state_dict(), save_model+'.pt')
                    # new_flag = 1

    


if __name__ == '__main__':
    # need to add argparse
    # run(mode=args.mode, root=args.root, save_model=args.save_model)
    run()
